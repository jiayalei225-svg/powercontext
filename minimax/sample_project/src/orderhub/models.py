"""订单域模型。

业务工程 orderhub 的领域对象定义。保持纯标准库实现，便于评审在干净环境直接运行。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

#: 订单状态机中允许出现的状态值。
ALLOWED_STATUSES: tuple[str, ...] = (
    "pending",
    "paid",
    "shipped",
    "delivered",
    "cancelled",
)


def parse_iso8601(value: str) -> datetime:
    """解析 ISO8601 时间字符串，统一为 UTC 时区。

    支持 ``2026-03-01`` 与 ``2026-03-01T08:30:00+08:00`` 两种写法。
    """
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_iso8601(value: datetime) -> str:
    """把时间序列化为带 Z 后缀的 UTC 字符串。"""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class Order:
    """一条订单记录。"""

    id: str
    customer: str
    status: str
    total_cents: int
    created_at: datetime
    channel: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Order":
        return cls(
            id=str(raw["id"]),
            customer=str(raw["customer"]),
            status=str(raw["status"]),
            total_cents=int(raw["total_cents"]),
            created_at=parse_iso8601(str(raw["created_at"])),
            channel=str(raw["channel"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "customer": self.customer,
            "status": self.status,
            "total_cents": self.total_cents,
            "created_at": format_iso8601(self.created_at),
            "channel": self.channel,
        }
