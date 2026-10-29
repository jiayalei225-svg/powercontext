"""订单查询服务。

本模块承载订单列表的核心查询语义：排序、分页。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import ApiError, InvalidPageSize
from .models import Order
from .repository import OrderRepository


@dataclass(frozen=True, slots=True)
class OrderPage:
    """一页订单查询结果。"""

    items: list[Order]
    total: int
    page: int
    page_size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [order.to_dict() for order in self.items],
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
        }


def _parse_positive_int(raw: str | None, *, field: str, default: int) -> int:
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ApiError("invalid_pagination", f"{field} 必须是整数") from exc
    if value < 1:
        raise ApiError("invalid_pagination", f"{field} 必须大于 0")
    return value


class OrderService:
    """订单查询服务。"""

    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 100

    def __init__(self, repository: OrderRepository) -> None:
        self._repository = repository

    def get_order(self, order_id: str) -> Order:
        """按 ID 返回单条订单，不存在时抛 :class:`OrderNotFoundError`。"""
        return self._repository.get(order_id)

    def list_orders(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> OrderPage:
        """返回分页后的订单列表。

        排序固定为 ``created_at`` 降序、``id`` 降序，保证翻页结果稳定。
        """
        if page_size < 1 or page_size > self.MAX_PAGE_SIZE:
            raise InvalidPageSize(self.MAX_PAGE_SIZE)
        if page < 1:
            raise ApiError("invalid_pagination", "page 必须大于 0")

        ordered = sorted(
            self._repository.all(),
            key=lambda order: (order.created_at, order.id),
            reverse=True,
        )
        total = len(ordered)
        start = (page - 1) * page_size
        return OrderPage(
            items=ordered[start : start + page_size],
            total=total,
            page=page,
            page_size=page_size,
        )
