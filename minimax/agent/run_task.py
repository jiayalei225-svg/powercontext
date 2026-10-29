"""开发助手编排：上下文 → MiniMax → 落地代码 → 记录开发日志。

用法：

    python -m agent.run_task --task samples/task.json --attempt 1
    python -m agent.run_task --task samples/task.json --dry-run   # 只打印将要发送的 prompt

为什么让模型输出"整份文件"而不是 unified diff：模型生成的 diff 行号与上下文
极易错位，落地失败会把"代码修改有效"变成环境问题。整份文件写入是确定性的，
真正的代码差异由 ``git diff`` 生成，仍然可核对。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sddctx.config import Settings
from sddctx.selector import ContextBuilder
from sddctx.state import PowerContextState
from sddctx.store import SeekDBStore

from .minimax_client import MiniMaxClient, MiniMaxError

#: 最多随 prompt 发送的代码文件数（控制 token，适配 MiniMax 账号 TPM 限额）
MAX_CODE_FILES = 4

#: 单次请求的 TPM 预算（prompt_tokens + max_tokens）。
#: 实测该账号约 10K TPM：3107+4000 通过，6000+8000 触发 1039。
TPM_BUDGET = 9_000

SYSTEM_PROMPT = """你是一名严格遵守规格驱动开发（SDD）约束的 Python 工程师。

工作规则：
1. 只能修改用户指定的目标文件，不要新增文件，不要改动测试。
2. 逐条满足规格；规格中"兼容性约束"部分列出的既有行为一条都不能破坏。
3. 不要引入新的第三方依赖，只用标准库与工程现有依赖。
4. 代码需保持工程既有风格（类型标注、docstring、错误码结构）。
5. 输出必须是**一个 JSON 对象**，不要输出任何解释性文字或 Markdown 代码围栏。"""

OUTPUT_CONTRACT = """输出 JSON 结构：
{
  "summary": "一句话说明改了什么",
  "spec_coverage": [{"spec_id": "SPEC-ORD-014", "how": "如何满足"}],
  "files": [{"path": "src/orderhub/api.py", "content": "该文件修改后的完整内容"}]
}

要求：
- files 必须覆盖所有需要修改的目标文件，content 是该文件的**完整可运行内容**（不是片段、不是 diff）。
- JSON 字符串中的换行必须正确转义；不要使用 Markdown 围栏。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def estimate_tokens(text: str) -> int:
    """粗估 token 数：中日韩字符约 1.5 字符/token，其余约 3.5 字符/token。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return int(cjk / 1.5 + other / 3.5) + 8


def assert_assertions(test_path: Path, limit: int = 40) -> str:
    """抽取测试文件里每个用例的断言，作为"必须满足的行为"清单（比全文省很多 token）。"""
    import ast

    raw = test_path.read_text(encoding="utf-8")
    tree = ast.parse(raw)
    lines = raw.splitlines()
    bullets: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test"):
            continue
        doc = (ast.get_docstring(node) or "").split("\n")[0].strip()
        asserts: list[str] = []
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assert):
                segment = ast.get_source_segment(raw, sub) or ""
                asserts.append(" ".join(segment.split()))
            elif isinstance(sub, ast.With):
                for item in sub.items:
                    call = item.context_expr
                    if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "raises":
                        segment = ast.get_source_segment(raw, sub) or ""
                        first_line = segment.splitlines()[0].strip()
                        asserts.append(f"{first_line} …")
        if not asserts:
            continue
        head = f"- {node.name}：{doc}" if doc else f"- {node.name}"
        bullets.append(head)
        for assertion in asserts[:3]:
            bullets.append(f"    · {assertion}")
        if len(bullets) >= limit:
            break
    return "\n".join(bullets)


def build_prompt(
    task: dict[str, Any],
    context: dict[str, Any],
    project_root: Path,
    *,
    focus: str | None = None,
    done_notes: list[str] | None = None,
    feedback: str | None = None,
    token_budget: int | None = None,
) -> tuple[str, list[str]]:
    """把上下文渲染成给模型的单条 user prompt，返回 (prompt, 读取的文件列表)。

    ``focus`` 指定本次只生成本文件（按文件分步生成，把单次请求压进 TPM 限额）。
    聚焦模式下：

    - 规格只发 ``code_refs`` 命中该文件、或属于兼容性/响应结构这类全局条款的；
    - 测试只发断言摘要（不发全文），既满足"知道必须通过什么"，又省 token。
    """
    budget = token_budget or TPM_BUDGET

    if focus:
        related = [
            item
            for item in context["spec_items"]
            if any(ref.startswith(focus + "::") or ref == focus for ref in item.get("code_refs") or [])
            or item["id"] in ("SPEC-ORD-001", "SPEC-ORD-030")
        ]
        if not related:
            related = context["spec_items"]
    else:
        related = context["spec_items"]

    spec_blocks = []
    for item in related:
        spec_blocks.append(
            f"### {item['id']} {item['title']}（来源 {item['source']}）\n{item['text']}"
        )

    # 1. 代码：聚焦模式只发目标文件；否则优先"被规格引用 / 任务声明路径"
    if focus:
        selected_paths = [focus]
    else:
        def priority(entry: dict[str, Any]) -> tuple[int, float]:
            reasons = " ".join(entry.get("reason") or [])
            strong = "referenced_by_spec" in reasons or "touched_path" in reasons
            return (0 if strong else 1, -entry.get("score", 0.0))

        selected_paths = []
        for entry in sorted(context["code_targets"], key=priority):
            if entry["path"] not in selected_paths:
                selected_paths.append(entry["path"])
            if len(selected_paths) >= MAX_CODE_FILES:
                break

    code_blocks = []
    read_files: list[str] = []
    for rel in selected_paths:
        path = project_root / rel
        if not path.is_file():
            continue
        read_files.append(rel)
        code_blocks.append(f"### {rel}\n```python\n{path.read_text(encoding='utf-8')}\n```")

    # 2. 测试：聚焦模式用断言摘要，全量模式发功能测试全文
    if focus:
        functional_files = sorted({case["path"] for case in context["tests"]["functional"]})
        summaries = []
        for rel in functional_files:
            path = project_root / rel
            if path.is_file():
                summaries.append(f"### {rel} 的断言（必须满足，不得修改测试）\n{assert_assertions(path)}")
        test_section = "\n\n".join(summaries)
    else:
        functional_files = sorted({case["path"] for case in context["tests"]["functional"]})
        blocks = []
        for rel in functional_files:
            path = project_root / rel
            if path.is_file():
                blocks.append(f"### {rel}（必须全部通过，不得修改）\n```python\n{path.read_text(encoding='utf-8')}\n```")
        test_section = "\n\n".join(blocks)

    regression_lines = []
    for case in context["tests"]["regression"]:
        covers = ",".join(case.get("covers") or []) or "-"
        regression_lines.append(f"- {case['path']}::{case['id']}（覆盖 {covers}）")

    lines = [
        "## 开发任务",
        f"任务编号：{task['task_id']}",
        f"标题：{task['title']}",
        task["description"],
        "",
        "### 验收要点",
        *[f"- {item}" for item in task.get("acceptance", [])],
        "",
        "## 必须遵守的规格条目（来自工程规格库）",
        "\n\n".join(spec_blocks),
        "",
        "## 相关代码（当前工作区实际内容）",
        "\n\n".join(code_blocks),
        "",
        "## 必须满足的测试行为",
        test_section,
        "",
        "### 同时不得破坏的既有回归测试",
        *regression_lines,
    ]

    if done_notes:
        lines += ["", "## 本任务已完成的步骤（不要重复实现，直接复用其结果）", *[f"- {note}" for note in done_notes]]

    if feedback:
        lines += [
            "",
            "## 上一轮验证失败（必须修复，测试不得修改）",
            feedback,
        ]

    if focus:
        lines += [
            "",
            "## 输出",
            f"只输出文件 {focus} 修改后的**完整内容**，用一个 JSON 对象：",
            '{"summary": "一句话说明改了什么", "spec_coverage": [{"spec_id": "...", "how": "..."}], '
            f'"files": [{{"path": "{focus}", "content": "完整文件内容"}}]}}',
            "不要输出其他文件，不要输出 Markdown 围栏，JSON 字符串里的换行要正确转义。",
        ]
    else:
        lines += ["", "## 输出", OUTPUT_CONTRACT]

    prompt = "\n".join(lines)
    return prompt, read_files


def parse_model_output(text: str) -> dict[str, Any]:
    """从模型输出里抽出 JSON 对象（容忍 ```json 围栏）。"""
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("模型输出中没有 JSON 对象")
    return json.loads(cleaned[start : end + 1])


def write_files(payload: dict[str, Any], project_root: Path) -> list[str]:
    """把模型给出的文件内容写入工程，返回实际写入的相对路径。"""
    written: list[str] = []
    for entry in payload.get("files", []):
        rel = str(entry.get("path", "")).replace("\\", "/").lstrip("./")
        if not rel:
            continue
        target = (project_root / rel).resolve()
        if project_root.resolve() not in target.parents:
            raise ValueError(f"拒绝写入工程目录之外的文件：{rel}")
        if target.suffix != ".py":
            raise ValueError(f"只允许写入 Python 源文件：{rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        content = str(entry.get("content", ""))
        if not content.strip():
            raise ValueError(f"{rel} 内容为空")
        target.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
        written.append(rel)
    if not written:
        raise ValueError("模型没有返回任何文件")
    return written


def run_tests(project_root: Path, targets: list[str]) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "pytest", "-q", *targets]
    proc = subprocess.run(cmd, cwd=str(project_root), capture_output=True, text=True, encoding="utf-8")
    return {
        "command": "python -m pytest -q " + " ".join(targets),
        "exit_code": proc.returncode,
        "passed": proc.returncode == 0,
        "tail": (proc.stdout or "")[-2500:],
        "stderr_tail": (proc.stderr or "")[-1000:],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="用 MiniMax 完成一次 SDD 代码修改")
    parser.add_argument("--task", default="samples/task.json")
    parser.add_argument("--attempt", default="1", help="尝试编号，写进开发日志")
    parser.add_argument("--dry-run", action="store_true", help="只生成 prompt，不调用模型")
    parser.add_argument("--run-tests", action="store_true", help="写入后立刻跑目标测试")
    parser.add_argument(
        "--focus",
        default=None,
        help="只生成指定文件（相对工程根），用于按文件分步生成以适配 TPM 限额",
    )
    parser.add_argument(
        "--done",
        action="append",
        default=None,
        help="已完成的步骤说明，可重复，附在 prompt 里避免重复实现",
    )
    parser.add_argument(
        "--feedback",
        default=None,
        help="上一轮验证失败的摘要（测试输出），附在 prompt 里要求修复",
    )
    parser.add_argument(
        "--feedback-file",
        default=None,
        help="从文件读取失败摘要（便于在 shell 里传长文本）",
    )
    args = parser.parse_args(argv)

    if args.feedback_file and not args.feedback:
        args.feedback = Path(args.feedback_file).read_text(encoding="utf-8").strip()

    settings = Settings.load()
    task_path = Path(args.task)
    if not task_path.is_absolute():
        task_path = settings.module_root / task_path
    task = json.loads(task_path.read_text(encoding="utf-8"))
    project_root = settings.project_root

    store = SeekDBStore(settings.seekdb_path, query_log=settings.query_log)
    state = PowerContextState(settings.powercontext_url, settings.state_dir)
    context = ContextBuilder(store, state, budget_bytes=settings.budget_bytes).build(task)

    prompt, read_files = build_prompt(
        task,
        context,
        project_root,
        focus=args.focus,
        done_notes=args.done,
        feedback=args.feedback,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    # 按 TPM 预算动态决定输出上限：prompt + max_tokens 不超过预算
    prompt_tokens = estimate_tokens(SYSTEM_PROMPT + prompt)
    max_tokens = max(1_500, min(settings.minimax_max_tokens, TPM_BUDGET - prompt_tokens))

    logs_dir = settings.module_root / "artifacts" / "logs" / "minimax"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    request_path = logs_dir / f"{stamp}_attempt{args.attempt}_request.json"
    request_path.write_text(
        json.dumps(
            {
                "attempt": args.attempt,
                "task_id": task["task_id"],
                "focus": args.focus,
                "model_hint": settings.minimax_model,
                "prompt_tokens_estimate": prompt_tokens,
                "max_tokens": max_tokens,
                "tpM_budget": TPM_BUDGET,
                "messages": messages,
                "context_refs": {
                    "spec_ids": [item["id"] for item in context["spec_items"]],
                    "code_targets": [item["source"] for item in context["code_targets"]],
                    "tests": {
                        key: [case["source"] for case in context["tests"][key]]
                        for key in ("functional", "regression")
                    },
                },
                "files_read_from_workspace": read_files,
                "done_notes": args.done,
                "feedback": args.feedback,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"prompt 已写入 {request_path}（{len(prompt)} 字符，约 {prompt_tokens} tokens，"
        f"max_tokens={max_tokens}）",
        flush=True,
    )

    if args.dry_run:
        print(prompt)
        return 0

    client = MiniMaxClient(
        api_key=settings.minimax_api_key,
        base_url=settings.minimax_base_url,
        model=settings.minimax_model,
        timeout=settings.minimax_timeout,
        max_tokens=max_tokens,
    )
    try:
        result = client.chat(messages, max_tokens=max_tokens)
    except MiniMaxError as exc:
        print(f"MiniMax 调用失败：{exc}", file=sys.stderr)
        return 3

    response_path = logs_dir / f"{stamp}_attempt{args.attempt}_response.json"
    response_path.write_text(
        json.dumps(
            {
                "model": result.model,
                "request_id": result.request_id,
                "latency_ms": result.latency_ms,
                "usage": result.usage,
                "attempts": result.attempts,
                "reasoning_present": result.reasoning_present,
                "reasoning_chars": result.reasoning_chars,
                "content": result.content,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"响应已写入 {response_path}", flush=True)

    try:
        payload = parse_model_output(result.content)
        written = write_files(payload, project_root)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"落地失败：{exc}", file=sys.stderr)
        payload = {"error": str(exc)}
        written = []

    test_result = None
    if args.run_tests and written:
        test_result = run_tests(project_root, task.get("test_targets") or ["-q"])

    entry = {
        "ts": _now(),
        "attempt": args.attempt,
        "task_id": task["task_id"],
        "focus": args.focus,
        "model": result.model,
        "request_id": result.request_id,
        "prompt_sha256": _sha(prompt),
        "prompt_chars": len(prompt),
        "prompt_tokens_estimate": prompt_tokens,
        "max_tokens": max_tokens,
        "prompt_file": str(request_path.relative_to(settings.module_root)),
        "response_file": str(response_path.relative_to(settings.module_root)),
        "response_sha256": _sha(result.content),
        "latency_ms": result.latency_ms,
        "usage": result.usage,
        "reasoning_present": result.reasoning_present,
        "files_written": written,
        "summary": payload.get("summary"),
        "spec_coverage": payload.get("spec_coverage"),
        "error": payload.get("error"),
        "tests": test_result,
        "done_notes": args.done,
        "feedback": args.feedback,
        "context": {
            "spec_items": len(context["spec_items"]),
            "spec_ids_sent": [item["id"] for item in context["spec_items"]]
            if not args.focus
            else None,
            "code_targets": len(context["code_targets"]),
            "tests": len(context["tests"]["functional"]) + len(context["tests"]["regression"]),
            "seekdb_queries": store.query_count,
        },
    }
    devlog = settings.devlog_path
    devlog.parent.mkdir(parents=True, exist_ok=True)
    with devlog.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(json.dumps(entry, ensure_ascii=False, indent=2))
    return 0 if written and not payload.get("error") else 4


if __name__ == "__main__":
    raise SystemExit(main())
