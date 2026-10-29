"""HTTP 接入层。

为了让测试无需真实网络即可断言契约，路由逻辑实现为纯函数
:func:`handle_get_orders`；:func:`create_server` 只是把它挂到标准库
``http.server`` 上。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .errors import ApiError
from .repository import OrderNotFoundError
from .service import OrderService


def handle_get_orders(
    service: OrderService,
    query: Mapping[str, list[str]] | str,
) -> tuple[int, dict[str, Any]]:
    """处理 ``GET /orders``。

    ``query`` 可以是已解析的映射，也可以是原始查询串（便于测试）。
    """
    if isinstance(query, str):
        params: Mapping[str, list[str]] = parse_qs(query, keep_blank_values=True)
    else:
        params = query

    page_raw = _first(params, "page")
    page_size_raw = _first(params, "page_size")

    page = 1
    if page_raw not in (None, ""):
        try:
            page = int(page_raw)
        except ValueError:
            raise ApiError("invalid_pagination", "page 必须是整数") from None

    page_size = OrderService.DEFAULT_PAGE_SIZE
    if page_size_raw not in (None, ""):
        try:
            page_size = int(page_size_raw)
        except ValueError:
            raise ApiError("invalid_pagination", "page_size 必须是整数") from None

    result = service.list_orders(page=page, page_size=page_size)
    return 200, result.to_dict()


def handle_get_order(service: OrderService, order_id: str) -> tuple[int, dict[str, Any]]:
    """处理 ``GET /orders/{id}``。"""
    try:
        order = service.get_order(order_id)
    except OrderNotFoundError:
        raise ApiError("order_not_found", f"订单 {order_id} 不存在", status=404) from None
    return 200, order.to_dict()


def _first(params: Mapping[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    return values[0]


def dispatch(service: OrderService, path: str, query: Mapping[str, list[str]] | str):
    """把路径分派到对应处理函数。"""
    if path in ("/orders", "/orders/"):
        return handle_get_orders(service, query)
    if path.startswith("/orders/"):
        order_id = path[len("/orders/") :].strip("/")
        if order_id:
            return handle_get_order(service, order_id)
    if path == "/health":
        return 200, {"status": "ok"}
    raise ApiError("not_found", f"未知路径 {path}", status=404)


def make_handler(service: OrderService) -> type[BaseHTTPRequestHandler]:
    """基于纯函数路由构造 ``http.server`` 处理器。"""

    class Handler(BaseHTTPRequestHandler):
        server_version = "orderhub/0.4"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                status, payload = dispatch(service, parsed.path, parsed.query)
            except ApiError as exc:
                status, payload = exc.status, exc.to_payload()
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            if getattr(self.server, "verbose", False):
                super().log_message(fmt, *args)

    return Handler


def create_server(service: OrderService, host: str = "127.0.0.1", port: int = 8080):
    """创建（但不启动）一个 HTTP 服务器。"""
    return ThreadingHTTPServer((host, port), make_handler(service))
