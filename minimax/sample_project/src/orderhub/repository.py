"""订单仓储层。

种子数据来自 ``data/orders.json``。生产环境这里会接数据库，样例工程为了
可在评审环境直接运行，使用只读的 JSON 仓储。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from .models import Order


class OrderNotFoundError(KeyError):
    """按 ID 查找订单但不存在。"""


class OrderRepository:
    """内存订单仓储。"""

    def __init__(self, orders: Iterable[Order]) -> None:
        self._orders: tuple[Order, ...] = tuple(orders)
        self._by_id: dict[str, Order] = {order.id: order for order in self._orders}

    @classmethod
    def from_json_file(cls, path: str | Path) -> "OrderRepository":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "orders" not in payload:
            raise ValueError("orders.json 缺少 orders 字段")
        return cls(Order.from_dict(item) for item in payload["orders"])

    def all(self) -> list[Order]:
        """返回全部订单，顺序为数据文件顺序（未排序）。"""
        return list(self._orders)

    def get(self, order_id: str) -> Order:
        try:
            return self._by_id[order_id]
        except KeyError as exc:
            raise OrderNotFoundError(order_id) from exc

    def count(self) -> int:
        return len(self._orders)
