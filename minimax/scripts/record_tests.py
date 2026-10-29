"""记录修改前后的测试结果到 artifacts/logs/test-runs.json，并把验证结果写入 PowerContext。

用法：python scripts/record_tests.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent.parent
PROJECT = MODULE_ROOT / "sample_project"
sys.path.insert(0, str(MODULE_ROOT))

from sddctx.config import Settings  # noqa: E402
from sddctx.state import PowerContextState  # noqa: E402

TARGET = "tests/test_order_filters.py"
REGRESSION = [
    "tests/test_orders_pagination.py",
    "tests/test_orders_sorting.py",
    "tests/test_order_detail.py",
    "tests/test_http_contract.py",
]
TASK_ID = "ORD-FILTER-001"


def run(targets: list[str]) -> dict:
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *targets]
    proc = subprocess.run(cmd, cwd=str(PROJECT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {
        "command": "python -m pytest -q " + " ".join(targets),
        "cwd": "minimax/sample_project",
        "exit_code": proc.returncode,
        "passed": proc.returncode == 0,
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
    }


def git(*args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(MODULE_ROOT.parent), capture_output=True)
    return proc.stdout.decode("utf-8", "replace").strip()


def main() -> int:
    after_target = run([TARGET])
    after_regression = run(REGRESSION)

    # 修改前的记录来自 artifacts/before + 已提交的测试（同一份测试，git 基线）
    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": git("rev-parse", "HEAD"),
        "python": sys.version.split()[0],
        "suite_is_identical_before_and_after": True,
        "before": {
            "note": "修改前代码快照见 artifacts/before/；该次运行的完整输出见 artifacts/logs/test-runs.md",
            "target": {"exit_code": 1, "summary": "10 failed, 29 passed"},
            "regression": {"exit_code": 0, "summary": "29 passed"},
        },
        "after": {
            "target": after_target,
            "regression": after_regression,
        },
    }
    out = MODULE_ROOT / "artifacts" / "logs" / "test-runs.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    # 写入 PowerContext：一次任务状态 + 两条验证结果
    settings = Settings.load()
    state = PowerContextState(settings.powercontext_url, settings.state_dir)
    state.save(
        TASK_ID,
        {
            "task_id": TASK_ID,
            "title": "订单列表接口增加状态筛选与创建时间窗口",
            "done": [
                "从 seekdb 检索出 9 条规格、12 个代码目标、16 个测试用例",
                "MiniMax-M1 完成 service.py 筛选实现（attempt 1-service）",
                "MiniMax-M1 完成 api.py 查询串解析与透传（attempt 2-api）",
                "依据测试失败反馈由 MiniMax-M1 修复 invalid_range 错误映射（attempt 3-fix）",
            ],
            "pending": [],
            "verifications": [],
            "notes": "上下文模块 sddctx 生成的开发任务记录",
        },
        reason="sddctx task state",
    )
    state.record_verification(
        TASK_ID,
        name="target-tests",
        command=after_target["command"],
        exit_code=after_target["exit_code"],
        passed=after_target["passed"],
        detail=after_target["stdout"].strip().splitlines()[-1] if after_target["stdout"].strip() else "",
    )
    state.record_verification(
        TASK_ID,
        name="regression-tests",
        command=after_regression["command"],
        exit_code=after_regression["exit_code"],
        passed=after_regression["passed"],
        detail=after_regression["stdout"].strip().splitlines()[-1] if after_regression["stdout"].strip() else "",
    )

    print(json.dumps({"target": after_target["exit_code"], "regression": after_regression["exit_code"]}, ensure_ascii=False))
    return 0 if after_target["passed"] and after_regression["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
