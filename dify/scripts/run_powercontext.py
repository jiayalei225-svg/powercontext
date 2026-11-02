# -*- coding: utf-8 -*-
"""启动本地 PowerContext Server（SQLite 后端）。

默认把数据放在 ASCII 路径下，避免 Windows 中文路径在部分 Python/嵌入式
组件里的兼容问题。Dify 跑在 Docker 里时，Server 需要监听 0.0.0.0，
并通过 host.docker.internal 访问；只在本机使用时可以加 --host 127.0.0.1。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn
from powercontext.builtin.persistence.sqlite.profile import SQLiteConfig
from powercontext.server.factory import create_server_app
from powercontext.server.settings import HttpConfig, ServerSettings


def default_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "Moonfall" / "powercontext"
    return Path.home() / ".local" / "share" / "moonfall" / "powercontext"


def main() -> int:
    parser = argparse.ArgumentParser(description="启动月蚀镇 PowerContext Server")
    parser.add_argument("--data-dir", default=os.environ.get("POWERCONTEXT_DATA_DIR") or str(default_data_dir()))
    parser.add_argument("--host", default=os.environ.get("POWERCONTEXT_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("POWERCONTEXT_PORT", "8099")))
    args = parser.parse_args()

    workspace = Path(args.data_dir).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    database_file = workspace / "powercontext.sqlite3"

    settings = ServerSettings(
        workspace=workspace,
        public_url=f"http://{args.host}:{args.port}",
        allow_insecure_http=True,
        allow_unauthenticated_non_loopback=args.host not in {"127.0.0.1", "localhost"},
        http=HttpConfig(host=args.host, port=args.port),
        database=SQLiteConfig(url=f"sqlite+aiosqlite:///{database_file.as_posix()}"),
    )
    print(f"PowerContext server -> http://{args.host}:{args.port} (db={database_file})", flush=True)
    app = create_server_app(settings=settings)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
