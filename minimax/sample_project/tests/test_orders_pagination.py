"""回归：分页契约。

这些用例在本次修改前后都必须通过，防止新增筛选项破坏既有分页语义。
"""

from __future__ import annotations

import pytest

from orderhub.api import handle_get_orders
from orderhub.app import build_service
from orderhub.errors import ApiError


@pytest.fixture()
def service():
    return build_service()


def test_default_page_size_is_20(service):
    """SPEC-ORD-030：不带 page_size 时默认 20，且与修改前一致。"""
    status, payload = handle_get_orders(service, "")
    assert status == 200
    assert payload["page"] == 1
    assert payload["page_size"] == 20
    assert payload["total"] == 16
    assert len(payload["items"]) == 16


def test_page_size_limits_items_but_keeps_total(service):
    status, payload = handle_get_orders(service, "page_size=5")
    assert status == 200
    assert len(payload["items"]) == 5
    assert payload["total"] == 16


def test_last_page_may_be_partial(service):
    status, payload = handle_get_orders(service, "page=4&page_size=5")
    assert status == 200
    assert len(payload["items"]) == 1
    assert payload["total"] == 16


def test_page_beyond_range_returns_empty_items(service):
    status, payload = handle_get_orders(service, "page=99&page_size=5")
    assert status == 200
    assert payload["items"] == []
    assert payload["total"] == 16


def test_pages_do_not_overlap_and_cover_all(service):
    seen: list[str] = []
    for page in range(1, 5):
        _, payload = handle_get_orders(service, f"page={page}&page_size=4")
        seen.extend(item["id"] for item in payload["items"])
    assert len(seen) == 16
    assert len(set(seen)) == 16


@pytest.mark.parametrize("raw_page_size", ["0", "-3", "101", "1000"])
def test_page_size_out_of_range_rejected(service, raw_page_size):
    with pytest.raises(ApiError) as excinfo:
        handle_get_orders(service, f"page_size={raw_page_size}")
    assert excinfo.value.code == "invalid_page_size"
    assert excinfo.value.status == 400


def test_page_size_max_boundary_accepted(service):
    status, payload = handle_get_orders(service, "page_size=100")
    assert status == 200
    assert payload["page_size"] == 100


@pytest.mark.parametrize("raw_page", ["0", "-1"])
def test_page_out_of_range_rejected(service, raw_page):
    with pytest.raises(ApiError) as excinfo:
        handle_get_orders(service, f"page={raw_page}")
    assert excinfo.value.code == "invalid_pagination"


def test_non_integer_page_size_rejected(service):
    with pytest.raises(ApiError) as excinfo:
        handle_get_orders(service, "page_size=abc")
    assert excinfo.value.code == "invalid_pagination"
