"""订单查询服务。

本模块承载订单列表的核心查询语义：排序、分页、筛选。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .errors import ApiError, InvalidPageSize
from .models import Order
from .repository import OrderRepository


VALID_STATUSES = frozenset({"pending", "paid", "shipped", "delivered", "cancelled"})


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


def _normalize_status(status: str) -> str:
    """规范化状态值：小写并去除两端空白。"""
    return status.strip().lower()


def _parse_datetime(raw: str | None) -> datetime | None:
    """解析时间字符串，支持 YYYY-MM-DD 与完整 ISO8601。

    仅给日期时 created_from 取 00:00:00，created_to 取 23:59:59.999999（UTC）。
    返回 UTC 时间。
    """
    if raw is None or raw == "":
        return None

    # 完整 ISO8601（含 Z 或偏移）
    iso_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:?\d{2}|Z)?$"
    date_only_pattern = r"^\d{4}-\d{2}-\d{2}$"

    if re.match(iso_pattern, raw):
        # 完整 ISO8601，解析并转为 UTC
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        # 转为 UTC
        return dt.astimezone(timezone.utc)

    if re.match(date_only_pattern, raw):
        # 仅日期，解析为当天的时间（UTC）
        dt = datetime.strptime(raw, "%Y-%m-%d")
        # created_from: 00:00:00 UTC
        # created_to: 23:59:59.999999 UTC
        return dt.replace(tzinfo=timezone.utc)

    raise ValueError(f"无法解析的时间格式: {raw}")


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
        status: list[str] | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
    ) -> OrderPage:
        """返回分页后的订单列表。

        排序固定为 ``created_at`` 降序、``id`` 降序，保证翻页结果稳定。

        Args:
            page: 页码，从 1 开始。
            page_size: 每页记录数。
            status: 订单状态列表，支持多值并集。不传或空等价于不过滤。
            created_from: 创建时间起始（闭区间）。
            created_to: 创建时间结束（闭区间）。
        """
        if page_size < 1 or page_size > self.MAX_PAGE_SIZE:
            raise InvalidPageSize(self.MAX_PAGE_SIZE)
        if page < 1:
            raise ApiError("invalid_pagination", "page 必须大于 0")

        # 解析并验证时间窗口
        try:
            from_dt = _parse_datetime(created_from)
            to_dt = _parse_datetime(created_to)
        except ValueError as exc:
            raise ApiError("invalid_range", "无效的时间格式") from exc

        # 处理仅日期的情况：from 取 00:00:00，to 取 23:59:59.999999
        if created_from and from_dt and not created_from.endswith(("Z", "+00:00", "+0000")) and "T" not in created_from:
            # 仅日期，from 已是 00:00:00 UTC，无需额外处理
            pass
        if created_to and to_dt and not created_to.endswith(("Z", "+00:00", "+0000")) and "T" not in created_to:
            # 仅日期，扩展到 23:59:59.999999 UTC
            to_dt = to_dt.replace(hour=23, minute=59, second=59, microsecond=999999)

        # 验证时间窗口：from <= to
        if from_dt and to_dt and from_dt > to_dt:
            raise ApiError("invalid_range", "created_from 不能晚于 created_to")

        # 解析并验证状态
        normalized_statuses: set[str] = set()
        if status:
            for s in status:
                if not s or s.strip() == "":
                    continue
                normalized = _normalize_status(s)
                if normalized not in VALID_STATUSES:
                    raise ApiError("invalid_status", f"非法订单状态: {s}")
                normalized_statuses.add(normalized)

        # 获取所有订单并应用筛选
        all_orders = self._repository.all()
        filtered = list(all_orders)

        # 状态筛选（并集）
        if normalized_statuses:
            filtered = [o for o in filtered if o.status.lower() in normalized_statuses]

        # 时间窗口筛选（闭区间，UTC 比较）
        if from_dt or to_dt:
            result: list[Order] = []
            for order in filtered:
                # 将订单创建时间归一化为 UTC
                order_dt = order.created_at
                if order_dt.tzinfo is None:
                    order_dt = order_dt.replace(tzinfo=timezone.utc)
                else:
                    order_dt = order_dt.astimezone(timezone.utc)

                # 闭区间检查
                if from_dt and order_dt < from_dt:
                    continue
                if to_dt and order_dt > to_dt:
                    continue
                result.append(order)
            filtered = result

        # 排序：created_at 降序，id 降序
        ordered = sorted(
            filtered,
            key=lambda order: (order.created_at, order.id),
            reverse=True,
        )

        # 计算总数（筛选后的）
        total = len(ordered)

        # 分页
        start = (page - 1) * page_size
        return OrderPage(
            items=ordered[start : start + page_size],
            total=total,
            page=page,
            page_size=page_size,
        )
