"""HTTP 调用入口（标准库实现，无额外 Web 框架依赖）。

    POST /context     body: 任务 JSON（同 samples/task.json）  → 开发上下文
    GET  /stats       → seekdb / PowerContext 状态
    GET  /health      → 存活探针

AGENT 侧（如 MCP 工具或插件）只需要 POST /context 拿上下文，再交给模型。
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .config import Settings
from .selector import ContextBuilder
from .state import PowerContextState
from .store import SeekDBStore


def build_context(payload: dict[str, Any], *, budget: int = 24_000) -> dict[str, Any]:
    settings = Settings.load()
    store = SeekDBStore(settings.seekdb_path, query_log=settings.query_log)
    state = PowerContextState(settings.powercontext_url, settings.state_dir)
    context = ContextBuilder(store, state, budget_bytes=budget).build(payload)
    context["seekdb"] = {
        "backend": store.backend_name,
        "counts": {kind: store.count(kind) for kind in ("spec", "code", "test")},
        "queries": store.query_count,
    }
    return context


def _make_handler() -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "sddctx/1.0"

        def _send(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/") in ("/health", ""):
                self._send(200, {"status": "ok", "module": "sddctx"})
                return
            if self.path.rstrip("/") == "/stats":
                settings = Settings.load()
                store = SeekDBStore(settings.seekdb_path, query_log=settings.query_log)
                state = PowerContextState(settings.powercontext_url, settings.state_dir)
                self._send(200, {"seekdb": store.stats(), "powercontext": state.health()})
                return
            self._send(404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path.rstrip("/") != "/context":
                self._send(404, {"error": "not_found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                payload = json.loads(raw)
                context = build_context(payload)
            except Exception as exc:  # noqa: BLE001
                self._send(400, {"error": "bad_request", "detail": f"{type(exc).__name__}: {exc}"})
                return
            self._send(200, context)

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            return

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8123) -> int:
    server = ThreadingHTTPServer((host, port), _make_handler())
    print(f"sddctx listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
