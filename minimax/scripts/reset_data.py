"""重置运行数据（回到"什么都没有"的状态）。

    python scripts/reset_data.py              # 清空 seekdb 与状态缓存
    python scripts/reset_data.py --keep-logs  # 同时保留 artifacts/logs 历史

会删除 ``minimax/.data/``（seekdb 数据目录 + PowerContext Scope 缓存）。
PowerContext Server 端的 Memory 记录属于服务侧数据，如需彻底清空，
请同时删除 Server 的 ``--data-dir`` 后重新启动。
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="重置 sddctx 运行数据")
    parser.add_argument("--data-dir", default=str(MODULE_ROOT / ".data"))
    parser.add_argument("--keep-logs", action="store_true")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)
        print(f"removed {data_dir}")
    else:
        print(f"{data_dir} 不存在，无需删除")

    if not args.keep_logs:
        for path in (
            MODULE_ROOT / "artifacts" / "logs" / "seekdb-queries.jsonl",
            MODULE_ROOT / "artifacts" / "context" / "context.json",
        ):
            if path.exists():
                path.unlink()
                print(f"removed {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
