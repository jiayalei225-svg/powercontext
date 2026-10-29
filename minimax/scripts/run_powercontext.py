"""以本地 SQLite 后端启动一个 PowerContext Server（供 sddctx 保存/复读任务状态）。

不用交互式 ``powercontext config init`` 向导，而是直接用官方
``ServerSettings`` + ``create_server_app`` 组装，保证评审环境可一条命令复现。

    python scripts/run_powercontext.py --data-dir .data/powercontext --port 8099

停止：Ctrl+C。数据留在 ``--data-dir`` 下的 SQLite 文件中，因此 Server 重启后
任务状态仍然可读。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动一个本地 PowerContext Server")
    parser.add_argument("--data-dir", default=".data/powercontext", help="工作区与 SQLite 存放目录")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args(argv)

    try:
        import uvicorn
        from powercontext.builtin.persistence.sqlite.profile import SQLiteConfig
        from powercontext.server.factory import create_server_app
        from powercontext.server.settings import HttpConfig, ServerSettings
    except ImportError:
        print(
            "缺少 powercontext 依赖，请先执行：pip install 'powercontext[cli,server]==1.4.1'",
            file=sys.stderr,
        )
        return 2

    workspace = Path(args.data_dir).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    database_file = workspace / "powercontext.sqlite3"

    settings = ServerSettings(
        workspace=workspace,
        public_url=f"http://{args.host}:{args.port}",
        allow_insecure_http=True,
        http=HttpConfig(host=args.host, port=args.port),
        database=SQLiteConfig(url=f"sqlite+aiosqlite:///{database_file.as_posix()}"),
    )

    print(f"PowerContext server -> http://{args.host}:{args.port} (db={database_file})", flush=True)
    app = create_server_app(settings=settings)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
