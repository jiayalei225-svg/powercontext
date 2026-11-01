"""End-to-end acceptance check for a running StudyCoach instance.

Run it after the one-click start (or manual two-terminal start):

    python scripts/verify.py

It exercises the real HTTP surface in order and asks the same questions a
reviewer would: did seekdb return citable chunks, did PowerContext really get
read and written, did mastery move, did the plan reuse itself? Every step uses
a fresh session so the output stays readable; the run does write practice data
and memories, which is expected for an acceptance test.

No third-party dependencies: urllib only, so it runs in the same venv without
anything beyond requirements.txt.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE = "http://127.0.0.1:8090"
FAILURES: list[str] = []


def _reconfigure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def call(base: str, method: str, path: str, body: Any | None = None, timeout: int = 120) -> Any:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        raise RuntimeError(f"{method} {path} -> HTTP {error.code}: {detail[:600]}") from error


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}" + (f" · {detail}" if detail else ""))
    else:
        print(f"  FAIL  {name}" + (f" · {detail}" if detail else ""))
        FAILURES.append(name)


def step(title: str) -> None:
    print(f"\n[{title}]")


def main() -> int:
    parser = argparse.ArgumentParser(description="StudyCoach acceptance check")
    parser.add_argument("--base", default=DEFAULT_BASE, help="StudyCoach base URL")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    session_1 = f"verify-{stamp}-1"
    session_2 = f"verify-{stamp}-2"
    session_quiz = f"verify-{stamp}-quiz"
    session_plan = f"verify-{stamp}-plan"

    _reconfigure_stdout()
    print(f"StudyCoach acceptance · {base}")

    step("1. 健康检查")
    health = call(base, "GET", "/health", timeout=20)
    check("应用返回 ok", health.get("status") == "ok", f"stage={health.get('stage')}")
    check("seekdb 已连接", (health.get("integrations") or {}).get("seekdb", {}).get("status") == "ok")
    check("PowerContext ready", (health.get("integrations") or {}).get("powercontext", {}).get("ready") is True)
    embedding = (health.get("integrations") or {}).get("embedding") or {}
    check("本地嵌入可用", embedding.get("mode") == "local", f"{embedding.get('model')} · {embedding.get('dimension')}d")
    if FAILURES:
        print("\n前置条件不满足，后续步骤跳过。先按 README 启动应用与 PowerContext。")
        return 1

    step("2. 导入种子资料（幂等）")
    seeded = call(base, "POST", "/api/ingest/seed", {"session_id": session_1})
    stats = seeded.get("stats") or {}
    documents = int(stats.get("documents") or 0)
    chunks = int(stats.get("chunks") or 0)
    skipped = sum(1 for item in seeded.get("results") or [] if item.get("skipped"))
    check("文档已入库", documents >= 3, f"{documents} 份 · 本次跳过 {skipped}")
    check("chunk 已建索引", chunks >= 20, f"{chunks} chunks")

    step("3. 混合检索与引用契约")
    search = call(
        base,
        "POST",
        "/api/search",
        {"query": "正则化和过拟合是什么关系", "mode": "hybrid", "top_k": 5, "session_id": session_1},
    )
    results = search.get("results") or []
    check("返回检索结果", len(results) > 0, f"{len(results)} 条 · {search.get('mode')} · keywords={search.get('keywords')}")
    required = ("chunk_id", "doc_id", "doc_title", "section", "page")
    complete = bool(results) and all(key in (results[0] or {}) for key in required)
    check("每条结果带引用字段", complete, ", ".join(required))
    check("检索写入 trace", bool(search.get("trace_id")), str(search.get("trace_id")))
    if results:
        top = results[0]
        print(f"        top1: 《{top['doc_title']}》/ {top['section']} / p{top['page']} / {top['chunk_id']}")

    step("4. 第一轮问答（seekdb + PowerContext 同时调用）")
    ask_1 = call(
        base,
        "POST",
        "/api/ask",
        {"question": "正则化和过拟合是什么关系？", "session_id": session_1, "mode": "hybrid", "top_k": 5},
    )
    check("回答模式明确", ask_1.get("mode") in {"llm", "evidence"}, str(ask_1.get("mode")))
    check("回答引用了 seekdb 结果", len(ask_1.get("citations") or []) > 0, f"{len(ask_1.get('citations') or [])} 条引用")
    check("有 seekdb trace", bool((ask_1.get("trace_ids") or {}).get("seekdb")))
    check("有记忆 trace", bool((ask_1.get("trace_ids") or {}).get("memory")))
    check("返回回答正文", bool((ask_1.get("answer") or "").strip()))

    step("5. 会话收尾写回记忆")
    closed = call(
        base,
        "POST",
        "/api/session/close",
        {
            "session_id": session_1,
            "topic": "正则化与过拟合",
            "struggles": "L1 和 L2 的区别总是记反，权重衰减和早停的关系也没理清",
            "preference": "先给一句话结论，再配一个中文例子",
        },
    )
    written = closed.get("memories") or []
    kinds = sorted({item.get("kind") for item in written})
    existing = call(base, "GET", f"/api/memory?limit=50&session_id={session_1}").get("memories") or []
    all_kinds = {item.get("kind") for item in existing}
    check("收尾写入记忆", len(written) >= 1, f"本次新增 {len(written)} 条 · {kinds}")
    check("会话摘要存在", "session_summary" in kinds or "session_summary" in all_kinds)
    check("薄弱点存在", "weakness" in kinds or "weakness" in all_kinds,
          "相同卡点按幂等复用" if "weakness" not in kinds else "")
    check("偏好存在", "profile" in kinds or "profile" in all_kinds,
          "相同偏好按幂等复用" if "profile" not in kinds else "")
    counts = closed.get("trace_counts") or {}
    check("收尾轨迹覆盖两层", bool(counts.get("powercontext")) and bool(counts.get("app")), str(counts))

    step("6. 第二轮问答（跨会话记忆注入）")
    ask_2 = call(
        base,
        "POST",
        "/api/ask",
        {"question": "再讲讲正则化，我上次哪里没搞懂？", "session_id": session_2, "mode": "hybrid", "top_k": 5},
    )
    injected = ask_2.get("injected_memories") or []
    injected_kinds = sorted({item.get("kind") for item in injected})
    check("注入了跨会话记忆", len(injected) > 0, f"{len(injected)} 条 · {injected_kinds}")
    mentioned = "正则" in (ask_2.get("answer") or "") or "L1" in (ask_2.get("answer") or "")
    check("回答基于检索/记忆而非空话", mentioned)
    if injected:
        print(f"        first memory: [{injected[0].get('kind')}] {(injected[0].get('text') or '')[:80]}")

    step("7. 记忆列表")
    memory = call(base, "GET", "/api/memory?limit=50&session_id=" + session_2)
    memories = memory.get("memories") or []
    all_kinds = sorted({item.get("kind") for item in memories})
    check("记忆可列出", len(memories) >= 2, f"{len(memories)} 条 · {all_kinds}")
    check("五种 kind 已定义", {"profile", "weakness", "session_summary"}.issubset(set(all_kinds)))

    step("8. 今日复习队列")
    today = call(base, "GET", f"/api/review/today?limit=10&session_id={session_2}")
    queue = today.get("queue") or []
    review_stats = today.get("stats") or {}
    check("队列非空", len(queue) > 0, f"{len(queue)} 个 · due={review_stats.get('due')}")
    check("统计含到期数", int(review_stats.get("due") or 0) > 0)
    if queue:
        first = queue[0]
        check("队列项带掌握度状态", "state" in first and "next_review_label" in first, f"{first.get('name')} · {first.get('state')}")

    step("9. 出题、判分与掌握度")
    generated = call(base, "POST", "/api/quiz/generate", {"limit": 3, "session_id": session_quiz})
    questions = generated.get("questions") or []
    check("由原文生成题目", len(questions) >= 1, f"{len(questions)} 题 · {generated.get('selection')}")
    check("题目提供选项", bool(questions) and len(questions[0].get("options") or []) >= 2)
    answers = [
        {"question_id": item["question_id"], "chosen": (item.get("options") or [""])[0]}
        for item in questions
    ]
    submitted = call(
        base,
        "POST",
        "/api/quiz/submit",
        {"session_id": session_quiz, "answers": answers, "note": "验收脚本：故意选择第一个选项，用来验证错题归因"},
    )
    results = submitted.get("results") or []
    check("服务端完成判分", len(results) == len(answers), f"{len(results)} 题")
    if results:
        row = results[0]
        fields = ("mastery_before", "mastery_after", "answer", "explanation", "source_chunk_id", "next_review_at")
        check("结果含掌握度与出处", all(key in row for key in fields), f"mastery {row['mastery_before']} → {row['mastery_after']}")
        check("每题回链原文 chunk", all(item.get("source_chunk_id") for item in results))
        wrong = [item for item in results if not item.get("correct")]
        quiz_memory_kinds = sorted({item.get("kind") for item in submitted.get("memories") or []})
        check("练习进展写入 PowerContext", "task_state" in quiz_memory_kinds, str(quiz_memory_kinds))
        if wrong:
            check("答错写入错因记忆", "weakness" in quiz_memory_kinds, f"错 {len(wrong)} 题")
            print(f"        wrong example: 「{wrong[0]['kp_name']}」 next={wrong[0]['next_review_label']}")
        else:
            print("        本次选项恰好全对，未产生 weakness；掌握度仍会按答对更新。")
    check("判分写入 seekdb trace", bool(submitted.get("trace_id")), str(submitted.get("trace_id")))

    after = call(base, "GET", f"/api/review/today?limit=10&session_id={session_quiz}")
    after_stats = after.get("stats") or {}
    check("今日已答计数增加", int(after_stats.get("answered_today") or 0) >= len(answers), f"answered_today={after_stats.get('answered_today')}")

    step("10. 学习计划写入与复用")
    plan_1 = call(base, "POST", "/api/review/plan", {"days": 3, "limit": 5, "session_id": session_plan})
    plan_2 = call(base, "POST", "/api/review/plan", {"days": 3, "limit": 5, "session_id": session_plan})
    check("计划有正文", bool((plan_1.get("plan") or "").strip()), f"{len(plan_1.get('queue') or [])} 个知识点")
    check("计划写入 PowerContext", bool(plan_1.get("memories")), (plan_1.get("memories") or [{}])[0].get("artifact_id", ""))
    first_id = ((plan_1.get("memories") or [{}])[0]).get("artifact_id")
    second_id = ((plan_2.get("memories") or [{}])[0]).get("artifact_id")
    check("重复生成复用同一条", plan_2.get("reused") is True and first_id == second_id, f"{first_id} == {second_id}")

    step("11. 技术轨迹分层")
    traces = call(base, "GET", f"/api/traces?session_id={session_1}&limit=100").get("traces") or []
    layers = sorted({item.get("layer") for item in traces})
    check("有 seekdb 轨迹", "seekdb" in layers)
    check("有 PowerContext 轨迹", "powercontext" in layers)
    check("有应用轨迹", "app" in layers, str(layers))

    total = len(FAILURES)
    print("\n" + "=" * 60)
    if total:
        print(f"FAILED · {total} 项未通过：")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("ALL PASS · 问答、记忆、复习、计划与轨迹均已跑通")
    print(f"会话：{session_1} / {session_2} / {session_quiz} / {session_plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
