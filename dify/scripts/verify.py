# -*- coding: utf-8 -*-
"""月蚀镇一键验收。

前置：PowerContext 已启动（scripts/start.ps1 / start.sh），可选启动 narrator shim。
本脚本会：
1. 用真实 DSL 执行器跑完一局，检查 Dify 节点接线、PowerContext 存档、LLM 合并；
2. 换一个 conversation_id，用同一个 memory_id 开新局，检查 NPC 是否记得上一局；
3. 在第二局中途再换一个 conversation_id，检查是否从 PowerContext 续局；
4. 输出 evidence/logs/verify-report.json 与 evidence/verify-transcript.md。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from simulate_workflow import MiniDify, play_game  # noqa: E402

CHECKS = []


def check(ok, name, detail=""):
    CHECKS.append({"name": name, "ok": bool(ok), "detail": str(detail)})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    return bool(ok)


def wait_http(url, seconds=30):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            response = httpx.get(url, timeout=3)
            if response.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def ensure_shim(base, allow_start=True):
    root = base.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    health = root + "/health"
    if wait_http(health, 2):
        return None
    if not allow_start:
        return False
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "tools" / "openai_shim.py"), "--host", "127.0.0.1", "--port", "8101"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if wait_http(health, 20):
        return process
    return False


def scope_entries(base, scope_id):
    response = httpx.post(base.rstrip("/") + "/v1/memory/entries/list", json={"scope_id": scope_id, "limit": 100}, timeout=30)
    response.raise_for_status()
    return response.json().get("entries") or []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--powercontext", default="http://127.0.0.1:8099")
    parser.add_argument("--llm-base", default="http://127.0.0.1:8101/v1")
    parser.add_argument("--memory-id", default="verify-" + time.strftime("%Y%m%d%H%M%S"))
    parser.add_argument("--dsl", default=str(ROOT / "dsl" / "moonfall-werewolf.chatflow.yml"))
    parser.add_argument("--no-start-shim", action="store_true")
    args = parser.parse_args()

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "powercontext": args.powercontext,
        "llm_base": args.llm_base,
        "memory_id": args.memory_id,
        "checks": CHECKS,
        "transcript": [],
    }
    shim_process = None
    try:
        check(wait_http(args.powercontext.rstrip("/") + "/health/ready", 10), "PowerContext 就绪", args.powercontext)
        if not CHECKS[-1]["ok"]:
            return None
        shim_process = ensure_shim(args.llm_base, allow_start=not args.no_start_shim)
        shim_ok = shim_process is not False
        check(shim_ok, "narrator shim 可用（真实模型可跳过）", args.llm_base)

        # 第一局：完整跑完
        runner = MiniDify(args.dsl, powercontext=args.powercontext, llm_base=args.llm_base, user_id=args.memory_id, conversation_id="verify-conv-1")
        turns, state = play_game(runner, "seer")
        transcript = [{"turn": item["turn"], "query": item["query"], "phase": item["phase"], "answer": item["answer"]} for item in turns]
        report["transcript"] = transcript
        scope_id = runner.outputs.get("prep_scope", {}).get("scope_id", "")
        check(bool(scope_id), "PowerContext Scope 已创建", scope_id)
        check(state.get("phase") == "ended", "第一局正常结束", f"winner={state.get('winner')}")
        check(bool(state.get("match")), "第一局生成 match 记忆", json.dumps(state.get("match"), ensure_ascii=False)[:220])
        check(len(turns) >= 3, "第一局至少 3 个回合", f"{len(turns)} turns")
        check(any(item["phase"] == "day" for item in turns), "经历过白天讨论/投票")

        entries = scope_entries(args.powercontext, scope_id)
        check(len(entries) >= len(turns), "每回合都有 PowerContext 存档", f"{len(entries)} entries / {len(turns)} turns")
        ended = []
        for entry in entries:
            try:
                item = json.loads(entry.get("text") or "{}")
            except Exception:
                continue
            if item.get("status") == "ended" and item.get("match"):
                ended.append(item["match"])
        check(bool(ended), "PowerContext 中存在 ended 记忆", f"{len(ended)} matches")

        # 第二局：换 conversation_id，同一 memory_id；应引用上一局
        runner2 = MiniDify(args.dsl, powercontext=args.powercontext, llm_base=args.llm_base, user_id=args.memory_id, conversation_id="verify-conv-2")
        answer2 = runner2.turn("开始游戏", {"player_name": "验收员", "memory_id": args.memory_id})
        state2 = runner2.state()
        check("第 1 局" in answer2 or "第 2 局" in answer2, "新会话读到历史战绩", answer2[:300].replace("\n", " "))
        check(state2.get("phase") == "role_select", "新会话进入新一局选身份", str(state2.get("phase")))
        report["new_conversation_excerpt"] = answer2[:1500]

        # 中途续局：第二局选完身份后，再换一个会话
        answer3 = runner2.turn("预言家", {"player_name": "验收员", "memory_id": args.memory_id})
        state3 = runner2.state()
        check(state3.get("phase") == "night", "第二局进入夜晚", str(state3.get("phase")))
        runner3 = MiniDify(args.dsl, powercontext=args.powercontext, llm_base=args.llm_base, user_id=args.memory_id, conversation_id="verify-conv-3")
        answer4 = runner3.turn("开始游戏", {"player_name": "验收员", "memory_id": args.memory_id})
        state4 = runner3.state()
        check(state4.get("gid") == state3.get("gid"), "新会话续上同一局", f"{state4.get('gid')} vs {state3.get('gid')}")
        check("你已经在月蚀镇里了" in answer4, "续局提示正确", answer4[:200].replace("\n", " "))
        report["resume_excerpt"] = answer4[:1200]
        report["checks"] = CHECKS
        report["scope_id"] = scope_id
        report["entries"] = len(entries)
        report["match"] = state.get("match")
        report["turns"] = len(turns)

        # 证据文件
        evidence = ROOT / "evidence"
        (evidence / "logs").mkdir(parents=True, exist_ok=True)
        (evidence / "logs" / "verify-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = ["# 月蚀镇 · 验收记录", "", f"- 时间：{report['generated_at']}", f"- memory_id：{args.memory_id}", f"- scope_id：{scope_id}", ""]
        lines.append("## 第一局完整记录")
        for item in transcript:
            lines.append(f"### Turn {item['turn']} · `{item['query']}` · phase={item['phase']}")
            lines.append("")
            lines.append(item["answer"])
            lines.append("")
        lines.append("## 新会话读取历史战绩")
        lines.append("")
        lines.append(answer2)
        lines.append("")
        lines.append("## 新会话中途续局")
        lines.append("")
        lines.append(answer4)
        lines.append("")
        (evidence / "verify-transcript.md").write_text("\n".join(lines), encoding="utf-8")
        print(f"\nwrote {evidence / 'logs' / 'verify-report.json'}")
        print(f"wrote {evidence / 'verify-transcript.md'}")
    finally:
        if shim_process:
            shim_process.terminate()

    failed = [item for item in CHECKS if not item["ok"]]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    return report if not failed else None


if __name__ == "__main__":
    result = main()
    raise SystemExit(0 if result is not None else 1)
