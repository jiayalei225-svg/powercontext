"""回归：排序契约。

``created_at`` 降序、``id`` 降序，翻页结果必须稳定。
"""

from __future__ import annotations

import pytest

from orderhub.api import handle_get_orders
from orderhub.app import build_service


@pytest.fixture()
def service():
    return build_service()


def test_orders_sorted_by_created_at_desc(service):
    """SPEC-ORD-030：排序固定为 created_at 降序，筛选不得改变。"""
    _, payload = handle_get_orders(service, "page_size=100")
    timestamps = [item["created_at"] for item in payload["items"]]
    assert timestamps == sorted(timestamps, reverse=True)


def test_first_order_is_latest(service):
    _, payload = handle_get_orders(service, "page_size=100")
    assert payload["items"][0]["id"] == "ORD-1016"


def test_last_order_is_earliest(service):
    _, payload = handle_get_orders(service, "page_size=100")
    assert payload["items"][-1]["id"] == "ORD-1001"


def test_timezone_offsets_normalised_to_utc(service):
    _, payload = handle_get_orders(service, "page_size=100")
    by_id = {item["id"]: item["created_at"] for item in payload["items"]}
    # 2026-03-02T11:40:00+08:00 == 2026-03-02T03:40:00Z
    assert by_id["ORD-1002"] == "2026-03-02T03:40:00Z"


def test_sorting_stable_across_pages(service):
    _, first = handle_get_orders(service, "page=1&page_size=3")
    _, second = handle_get_orders(service, "page=2&page_size=3")
    ids = [item["id"] for item in first["items"] + second["items"]]
    assert ids == ["ORD-1016", "ORD-1015", "ORD-1014", "ORD-1013", "ORD-1012", "ORD-1011"]
