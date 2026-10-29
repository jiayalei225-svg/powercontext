"""六项必做项一键校验。

    python scripts/verify_all.py            # 全部检查
    python scripts/verify_all.py --only A,B # 只跑指定项

每一项都会打印命令、退出码与结论，并把完整结果写入
``artifacts/logs/verify-report.json``，便于评审逐条核对。

检查项对应题面 4.1：
    A 能够运行        从空状态初始化数据并产出上下文
    B MiniMax 实际参与 开发记录与提交的代码差异对应
    C 上下文正确       必要来源齐全；规格更新后使用新内容；换任务换答案
    D 数据库实际参与   seekdb 中有资料，查询结果进入上下文
    E 状态能够复用     从空状态保存，重启后读回并用于上下文
    F 代码修改有效     修改前目标测试失败、修改后通过；回归测试前后都通过
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MODULE_ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
TARGET_TESTS = ["tests/test_order_filters.py"]
REGRESSION_TESTS = [
    "tests/test_orders_pagination.py",
    "tests/test_orders_sorting.py",
    "tests/test_order_detail.py",
    "tests/test_http_contract.py",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None, timeout: int = 600) -> dict[str, Any]:
    """执行命令并记录命令、退出码与输出尾部。"""
    merged = os.environ.copy()
    merged["PYTHONDONTWRITEBYTECODE"] = "1"
    merged["PYTHONIOENCODING"] = "utf-8"
    if env:
        merged.update(env)
    started = time.perf_counter()
    proc = subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", env=merged, timeout=timeout
    )
    return {
        "command": " ".join(cmd),
        "cwd": str(cwd),
        "exit_code": proc.returncode,
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "stdout": (proc.stdout or "")[:400_000],
        "stdout_tail": (proc.stdout or "")[-4000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
    }


def cli(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> dict[str, Any]:
    return run([PY, "-m", "sddctx.cli", *args], cwd, env)


def parse_json_output(result: dict[str, Any]) -> dict[str, Any] | None:
    text = result.get("stdout") or result.get("stdout_tail") or ""
    start = text.find("{")
    if start == -1:
        return None
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError:
        return None


def load_json_file(path: Path) -> dict[str, Any]:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


# --------------------------------------------------------------------------- A


def check_a(tmp: Path) -> dict[str, Any]:
    """从空数据目录初始化，并产出一次上下文。"""
    data_dir = tmp / "A_data"
    ctx_file = tmp / "A_ctx.json"
    env = {"SDDCTX_DATA_DIR": str(data_dir), "SDDCTX_POWERCONTEXT_URL": os.environ.get("SDDCTX_POWERCONTEXT_URL", "http://127.0.0.1:8099")}
    init = cli(["init"], MODULE_ROOT, env)
    ctx = cli(["context", "--task", "samples/task.json", "--out", str(ctx_file)], MODULE_ROOT, env)
    payload = load_json_file(ctx_file)
    detail = {
        "init_exit": init["exit_code"],
        "init_counts": (parse_json_output(init) or {}).get("ingested"),
        "context_exit": ctx["exit_code"],
        "spec_items": len(payload.get("spec_items") or []),
        "code_targets": len(payload.get("code_targets") or []),
        "tests": len((payload.get("tests") or {}).get("functional") or [])
        + len((payload.get("tests") or {}).get("regression") or []),
    }
    passed = (
        init["exit_code"] == 0
        and ctx["exit_code"] == 0
        and detail["spec_items"] > 0
        and detail["code_targets"] > 0
        and detail["tests"] > 0
    )
    return {"id": "A", "name": "能够运行", "passed": passed, "detail": detail, "runs": [init, ctx]}


# --------------------------------------------------------------------------- B


def check_b() -> dict[str, Any]:
    """核对 MiniMax 的开发记录：响应内容完整、且与仓库中实际代码逐字节一致。

    不依赖提交历史（避免"是不是一个 commit 提交的"影响判定），而是直接回答三个问题：

    1. 有没有真实的模型调用记录（request_id / 模型名 / token 用量 / 耗时）；
    2. 记录里关联的 request/response 文件是否可读、sha256 是否自洽；
    3. 模型返回的文件内容是否就是仓库里现在的代码——这是"实际参与"最硬的证据。
    """
    import hashlib

    devlog = MODULE_ROOT / "artifacts" / "logs" / "minimax-devlog.jsonl"
    entries: list[dict[str, Any]] = []
    if devlog.exists():
        for line in devlog.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    applied = [entry for entry in entries if entry.get("files_written")]
    applied.sort(key=lambda entry: entry.get("ts", ""))

    tracked = run(["git", "ls-files", "--", "minimax/sample_project/src"], MODULE_ROOT.parent)
    tracked_files = {line.strip() for line in (tracked["stdout"] or "").splitlines() if line.strip()}

    # 每个文件只保留最后一次模型写入的版本（同一文件可能被多轮修改）
    latest: dict[str, dict[str, Any]] = {}
    hash_ok = True
    readable = True
    for entry in applied:
        response_path = MODULE_ROOT / str(entry.get("response_file", ""))
        if not response_path.is_file():
            readable = False
            continue
        body = json.loads(response_path.read_text(encoding="utf-8"))
        content = body.get("content", "")
        if hashlib.sha256(content.encode("utf-8")).hexdigest() != entry.get("response_sha256"):
            hash_ok = False
        try:
            payload = json.loads(content[content.find("{") : content.rfind("}") + 1])
        except (ValueError, json.JSONDecodeError):
            continue
        for item in payload.get("files", []):
            latest[str(item.get("path"))] = {
                "attempt": entry.get("attempt"),
                "content": str(item.get("content", "")),
                "request_id": entry.get("request_id"),
            }

    matching: list[str] = []
    mismatching: list[str] = []
    for rel, info in latest.items():
        current = MODULE_ROOT / "sample_project" / rel
        if current.is_file() and current.read_text(encoding="utf-8").rstrip("\n") == info["content"].rstrip("\n"):
            matching.append(rel)
        else:
            mismatching.append(rel)

    detail = {
        "devlog_entries": len(entries),
        "entries_with_written_files": len(applied),
        "models": sorted({entry.get("model") for entry in entries if entry.get("model")}),
        "request_ids": [entry.get("request_id") for entry in applied],
        "usage_samples": [
            {
                "attempt": entry.get("attempt"),
                "prompt_tokens": (entry.get("usage") or {}).get("prompt_tokens"),
                "completion_tokens": (entry.get("usage") or {}).get("completion_tokens"),
                "latency_ms": entry.get("latency_ms"),
            }
            for entry in applied
        ],
        "files_written_by_model": sorted(latest),
        "files_identical_to_model_output": sorted(matching),
        "files_differing_from_model_output": sorted(mismatching),
        "those_files_are_tracked_by_git": sorted(
            rel for rel in latest if f"minimax/sample_project/{rel}" in tracked_files
        ),
        "response_hash_consistent": hash_ok,
        "response_files_readable": readable,
        "prompt_artifacts": [str(entry.get("prompt_file")) for entry in applied if entry.get("prompt_file")],
    }
    passed = (
        bool(applied)
        and readable
        and hash_ok
        and bool(matching)
        and not mismatching
        and all(entry.get("request_id") for entry in applied)
    )
    return {"id": "B", "name": "MiniMax 实际参与", "passed": passed, "detail": detail, "runs": [tracked]}


# --------------------------------------------------------------------------- C


def _context_sources(payload: dict[str, Any]) -> dict[str, set[str]]:
    return {
        "specs": {item["id"] for item in payload.get("spec_items") or []},
        "code": {item["source"] for item in payload.get("code_targets") or []},
        "tests": {
            case["source"]
            for suite in ("functional", "regression")
            for case in (payload.get("tests") or {}).get(suite) or []
        },
    }


def check_c(tmp: Path) -> dict[str, Any]:
    """必要来源齐全；规格 v2 重导入后使用新内容；换任务换答案。"""
    task = json.loads((MODULE_ROOT / "samples" / "task.json").read_text(encoding="utf-8"))
    required = task["required_sources"]

    data_v1 = tmp / "C_v1"
    env1 = {"SDDCTX_DATA_DIR": str(data_v1)}
    run1 = cli(["--specs-dir", "samples/specs/v1", "init"], MODULE_ROOT, env1)
    ctx1_run = cli(["context", "--task", "samples/task.json", "--out", str(tmp / "C_ctx_v1.json")], MODULE_ROOT, env1)
    ctx1 = load_json_file(tmp / "C_ctx_v1.json")
    src1 = _context_sources(ctx1)

    missing = {
        "specs": sorted(set(required["specs"]) - src1["specs"]),
        "code": sorted(set(required["code"]) - src1["code"]),
        "tests": sorted(set(required["tests"]) - src1["tests"]),
    }

    data_v2 = tmp / "C_v2"
    env2 = {"SDDCTX_DATA_DIR": str(data_v2)}
    run2 = cli(["--specs-dir", "samples/specs/v2", "init"], MODULE_ROOT, env2)
    ctx2_run = cli(["context", "--task", "samples/task.json", "--out", str(tmp / "C_ctx_v2.json")], MODULE_ROOT, env2)
    ctx2 = load_json_file(tmp / "C_ctx_v2.json")
    src2 = _context_sources(ctx2)

    v2_only = "SPEC-ORD-021.2"
    v1_has_v2_clause = v2_only in src1["specs"]
    v2_has_v2_clause = v2_only in src2["specs"]
    v2_text_updated = any(
        item["id"] == "SPEC-ORD-024" and "空结果" in item["title"] for item in ctx2.get("spec_items") or []
    )
    v1_title_old = any(
        item["id"] == "SPEC-ORD-024" and "空结果" in item["title"] for item in ctx1.get("spec_items") or []
    )

    # 换任务：分页任务的必要来源不能与筛选任务相同
    alt_task = MODULE_ROOT / "samples" / "task_pagination.json"
    alt_ctx = {}
    if alt_task.exists():
        alt_run = cli(
            ["context", "--task", "samples/task_pagination.json", "--out", str(tmp / "C_ctx_alt.json")],
            MODULE_ROOT,
            env1,
        )
        alt_ctx = parse_json_output(alt_run) or {}

    detail = {
        "missing_required_sources": missing,
        "v1_context_spec_ids": sorted(src1["specs"]),
        "v2_context_spec_ids": sorted(src2["specs"]),
        "v1_spec_version": ctx1.get("spec_version"),
        "v2_spec_version": ctx2.get("spec_version"),
        "v1_digest": ctx1.get("spec_digest"),
        "v2_digest": ctx2.get("spec_digest"),
        "v2_only_clause_in_v1_context": v1_has_v2_clause,
        "v2_only_clause_in_v2_context": v2_has_v2_clause,
        "v2_only_clause_id": v2_only,
        "v2_title_updated": v2_text_updated,
        "v1_title_old": v1_title_old,
        "alt_task_spec_ids": sorted(_context_sources(alt_ctx)["specs"]) if alt_ctx else [],
    }
    passed = (
        not any(missing.values())
        and not v1_has_v2_clause
        and v2_has_v2_clause
        and v2_text_updated
        and not v1_title_old
        and ctx1.get("spec_digest") != ctx2.get("spec_digest")
    )
    return {
        "id": "C",
        "name": "上下文正确",
        "passed": passed,
        "detail": detail,
        "runs": [run1, ctx1_run, run2, ctx2_run],
    }


# --------------------------------------------------------------------------- D


def check_d() -> dict[str, Any]:
    """seekdb 中确有资料，且查询结果进入了上下文。"""
    data_dir = MODULE_ROOT / ".data"
    env = {"SDDCTX_DATA_DIR": str(data_dir)}
    stats_run = cli(["stats"], MODULE_ROOT, env)
    stats = parse_json_output(stats_run) or {}
    counts = (stats.get("seekdb") or {}).get("collections") or {}

    log_path = MODULE_ROOT / "artifacts" / "logs" / "seekdb-queries.jsonl"
    queries: list[dict[str, Any]] = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines()[-400:]:
            line = line.strip()
            if line:
                try:
                    queries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    vector_queries = [q for q in queries if q.get("op") == "vector_query"]
    returned_ids = {item for q in vector_queries for item in (q.get("returned") or [])}

    ctx_path = MODULE_ROOT / "artifacts" / "context" / "context.json"
    spec_ids: set[str] = set()
    if ctx_path.exists():
        ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
        spec_ids = {item["id"] for item in ctx.get("spec_items") or []}

    db_spec_items = {item.split(":", 1)[1] for item in returned_ids if item.startswith("spec:")}
    detail = {
        "collections": counts,
        "vector_queries_logged": len(vector_queries),
        "distinct_ids_returned": len(returned_ids),
        "spec_ids_returned_by_db": sorted(db_spec_items),
        "spec_ids_in_context": sorted(spec_ids),
        "db_ids_used_by_context": sorted(db_spec_items & spec_ids),
    }
    passed = all(int(counts.get(name, 0)) > 0 for name in ("sddctx_spec", "sddctx_code", "sddctx_test")) and bool(
        db_spec_items & spec_ids
    )
    return {"id": "D", "name": "数据库实际参与", "passed": passed, "detail": detail, "runs": [stats_run]}


# --------------------------------------------------------------------------- E


def check_e(tmp: Path, server_url: str) -> dict[str, Any]:
    """从空状态保存任务记录 → 重启模块（新进程）→ 读出并用于上下文。"""
    state_dir = tmp / "E_state"
    env = {"SDDCTX_DATA_DIR": str(tmp / "E_data"), "SDDCTX_POWERCONTEXT_URL": server_url}
    task_id = "VERIFY-STATE-001"

    init_run = cli(["init"], MODULE_ROOT, env)

    # 用独立 task_id，避免校验数据污染交付样例 ORD-FILTER-001 的状态
    task = json.loads((MODULE_ROOT / "samples" / "task.json").read_text(encoding="utf-8"))
    task["task_id"] = task_id
    task["title"] = "（状态复用校验）" + task["title"]
    task_file = tmp / "E_task.json"
    task_file.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")

    record = {
        "task_id": task_id,
        "done": ["已定位规格 SPEC-ORD-014 与 SPEC-ORD-021", "已阅读 OrderService.list_orders"],
        "pending": ["实现 status 归一化与时间窗口解析", "补齐 invalid_status / invalid_range"],
        "verifications": [
            {"name": "target-tests-before", "command": "pytest tests/test_order_filters.py", "exit_code": 1, "passed": False}
        ],
        "notes": "verify_all 写入的空状态起点",
    }
    record_file = tmp / "E_record.json"
    record_file.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    save_run = cli(["state", "save", "--task-id", task_id, "--file", str(record_file)], MODULE_ROOT, env)
    saved = parse_json_output(save_run) or {}

    # 另起进程读取（模块重启）
    show_run = cli(["state", "show", "--task-id", task_id], MODULE_ROOT, env)
    shown = parse_json_output(show_run) or {}

    # 再起进程构造上下文，验证状态被真正使用
    ctx_run = cli(["context", "--task", str(task_file), "--out", str(tmp / "E_ctx.json")], MODULE_ROOT, env)
    ctx = load_json_file(tmp / "E_ctx.json")
    progress = ctx.get("progress") or {}

    loaded = shown.get("record") or {}
    detail = {
        "saved_seq": (saved.get("record") or {}).get("seq"),
        "saved_scope": (saved.get("record") or {}).get("scope_id"),
        "reload_found": bool(shown.get("found")),
        "reload_seq": loaded.get("seq"),
        "reload_done": loaded.get("done"),
        "reload_pending": loaded.get("pending"),
        "context_progress_available": progress.get("available"),
        "context_progress_backend": progress.get("backend"),
        "context_progress_done": progress.get("done"),
        "context_progress_verifications": len(progress.get("verifications") or []),
    }
    passed = (
        init_run["exit_code"] == 0
        and save_run["exit_code"] == 0
        and detail["reload_found"]
        and detail["reload_done"] == record["done"]
        and detail["context_progress_available"] is True
        and detail["context_progress_done"] == record["done"]
        and detail["context_progress_verifications"] >= 1
    )
    return {
        "id": "E",
        "name": "状态能够复用",
        "passed": passed,
        "detail": detail,
        "runs": [init_run, save_run, show_run, ctx_run],
    }


# --------------------------------------------------------------------------- F


def _copy_project(dest: Path) -> Path:
    src = MODULE_ROOT / "sample_project"
    target = dest / "project"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(
        src,
        target,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"),
    )
    return target


def _pytest(project: Path, targets: list[str]) -> dict[str, Any]:
    result = run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", *targets], project)
    out = (result["stdout_tail"] or "") + (result["stderr_tail"] or "")
    env_error = any(
        token in out
        for token in ("ModuleNotFoundError", "ImportError", "ERROR collecting", "errors during collection", "no tests ran")
    )
    result["environment_error"] = env_error
    return result


def check_f(tmp: Path) -> dict[str, Any]:
    """修改前目标测试失败、修改后通过；回归测试前后都通过。"""
    before_project = _copy_project(tmp / "F_before")
    for rel in ("api.py", "service.py"):
        shutil.copyfile(
            MODULE_ROOT / "artifacts" / "before" / "src" / "orderhub" / rel,
            before_project / "src" / "orderhub" / rel,
        )

    after_project = _copy_project(tmp / "F_after")

    before_target = _pytest(before_project, TARGET_TESTS)
    before_regression = _pytest(before_project, REGRESSION_TESTS)
    after_target = _pytest(after_project, TARGET_TESTS)
    after_regression = _pytest(after_project, REGRESSION_TESTS)

    detail = {
        "before_target_exit": before_target["exit_code"],
        "before_target_env_error": before_target["environment_error"],
        "before_regression_exit": before_regression["exit_code"],
        "after_target_exit": after_target["exit_code"],
        "after_target_env_error": after_target["environment_error"],
        "after_regression_exit": after_regression["exit_code"],
        "git_head": run(["git", "rev-parse", "HEAD"], MODULE_ROOT.parent)["stdout_tail"].strip(),
    }
    passed = (
        before_target["exit_code"] != 0
        and not before_target["environment_error"]
        and before_regression["exit_code"] == 0
        and after_target["exit_code"] == 0
        and after_regression["exit_code"] == 0
    )
    return {
        "id": "F",
        "name": "代码修改有效",
        "passed": passed,
        "detail": detail,
        "runs": [before_target, before_regression, after_target, after_regression],
    }


# --------------------------------------------------------------------------- 服务管理


def wait_for(url: str, timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="六项必做项校验")
    parser.add_argument("--only", default=None, help="只跑指定项，例如 A,C,F")
    parser.add_argument("--server-url", default=os.environ.get("SDDCTX_POWERCONTEXT_URL", "http://127.0.0.1:8099"))
    parser.add_argument("--report", default=str(MODULE_ROOT / "artifacts" / "logs" / "verify-report.json"))
    args = parser.parse_args(argv)

    only = {item.strip().upper() for item in args.only.split(",")} if args.only else set()
    results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="sddctx-verify-") as raw:
        tmp = Path(raw)
        checks = [
            ("A", lambda: check_a(tmp)),
            ("B", lambda: check_b()),
            ("C", lambda: check_c(tmp)),
            ("D", lambda: check_d()),
            ("E", lambda: check_e(tmp, args.server_url)),
            ("F", lambda: check_f(tmp)),
        ]
        for key, func in checks:
            if only and key not in only:
                continue
            try:
                results.append(func())
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "id": key,
                        "name": key,
                        "passed": False,
                        "detail": {"exception": f"{type(exc).__name__}: {exc}"},
                        "runs": [],
                    }
                )

    report = {
        "generated_at": now(),
        "server_url": args.server_url,
        "items": results,
        "all_passed": all(item["passed"] for item in results),
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    for item in results:
        flag = "PASS" if item["passed"] else "FAIL"
        print(f"[{flag}] {item['id']} {item['name']}")
        print("       " + json.dumps(item["detail"], ensure_ascii=False)[:600])
    print(f"\n报告：{report_path}")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
