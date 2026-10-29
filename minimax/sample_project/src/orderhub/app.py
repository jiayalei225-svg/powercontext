"""开发态启动入口。

    python -m orderhub.app --port 8080
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .api import create_server
from .repository import OrderRepository
from .service import OrderService

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "orders.json"


def build_service(data_file: str | Path = DATA_FILE) -> OrderService:
    """按数据文件构造服务实例，供测试与 CLI 复用。"""
    return OrderService(OrderRepository.from_json_file(data_file))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="orderhub 本地服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data", default=str(DATA_FILE))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    server = create_server(build_service(args.data), args.host, args.port)
    server.verbose = args.verbose  # type: ignore[attr-defined]
    print(f"orderhub listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
