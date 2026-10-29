"""新增功能测试：订单列表的状态筛选与创建时间窗口。

用例依据规格 ``SPEC-ORD-014``（状态筛选）、``SPEC-ORD-021``（时间窗口）、
``SPEC-ORD-024``（组合筛选与 total 语义）、``SPEC-ORD-030``（兼容性）。

本文件在修改前应全部失败（筛选参数被忽略），修改后应全部通过；
测试集本身在修改前后保持一致，不允许为了让用例通过而改断言。
"""

from __future__ import annotations

import pytest

from orderhub.api import handle_get_orders
from orderhub.app import build_service
from orderhub.errors import ApiError

PAID_IDS = {"ORD-1001", "ORD-1006", "ORD-1007", "ORD-1011", "ORD-1014", "ORD-1016"}
SHIPPED_IDS = {"ORD-1002", "ORD-1008", "ORD-1013"}


@pytest.fixture()
def service():
    return build_service()


def _ids(payload):
    return {item["id"] for item in payload["items"]}


def test_filter_single_status(service):
    """SPEC-ORD-014：单个 status 只返回该状态的订单。"""
    status, payload = handle_get_orders(service, "status=paid&page_size=100")
    assert status == 200
    assert payload["total"] == 6
    assert _ids(payload) == PAID_IDS


def test_filter_multiple_statuses_is_union(service):
    """SPEC-ORD-014：重复出现的 status 按并集处理。"""
    status, payload = handle_get_orders(
        service, "status=paid&status=shipped&page_size=100"
    )
    assert status == 200
    assert payload["total"] == 9
    assert _ids(payload) == PAID_IDS | SHIPPED_IDS


def test_filter_status_is_case_insensitive(service):
    """SPEC-ORD-014.2：状态匹配不区分大小写。"""
    status, payload = handle_get_orders(service, "status=PAID&page_size=100")
    assert status == 200
    assert _ids(payload) == PAID_IDS


def test_filter_status_trims_whitespace(service):
    """SPEC-ORD-014.2：状态值两端空白不影响匹配。"""
    status, payload = handle_get_orders(service, "status=%20paid%20&page_size=100")
    assert status == 200
    assert _ids(payload) == PAID_IDS


def test_unknown_status_rejected(service):
    """SPEC-ORD-014.1：非法状态返回 400 / invalid_status。"""
    with pytest.raises(ApiError) as excinfo:
        handle_get_orders(service, "status=refunded")
    assert excinfo.value.code == "invalid_status"
    assert excinfo.value.status == 400


def test_empty_status_means_no_filter(service):
    """SPEC-ORD-014：status 为空等价于不过滤。"""
    status, payload = handle_get_orders(service, "status=&page_size=100")
    assert status == 200
    assert payload["total"] == 16


def test_filter_created_at_window_inclusive(service):
    """SPEC-ORD-021：时间窗口为闭区间，按 UTC 归一化后比较。"""
    status, payload = handle_get_orders(
        service,
        "created_from=2026-03-10&created_to=2026-03-20&page_size=100",
    )
    assert status == 200
    assert payload["total"] == 4
    assert _ids(payload) == {"ORD-1009", "ORD-1010", "ORD-1011", "ORD-1012"}


def test_filter_window_excludes_utc_shifted_order(service):
    """SPEC-ORD-021：+08:00 的订单按 UTC 归一化后落在窗口外。"""
    status, payload = handle_get_orders(
        service,
        "created_from=2026-03-10T00:00:00Z&created_to=2026-03-10T23:59:59Z&page_size=100",
    )
    assert status == 200
    assert "ORD-1008" not in _ids(payload)
    assert payload["total"] == 0


def test_reversed_window_rejected(service):
    """SPEC-ORD-021.1：created_from 晚于 created_to 返回 400 / invalid_range。"""
    with pytest.raises(ApiError) as excinfo:
        handle_get_orders(
            service,
            "created_from=2026-03-20&created_to=2026-03-10",
        )
    assert excinfo.value.code == "invalid_range"
    assert excinfo.value.status == 400


def test_invalid_date_format_rejected(service):
    """SPEC-ORD-021.1：无法解析的时间返回 400 / invalid_range。"""
    with pytest.raises(ApiError) as excinfo:
        handle_get_orders(service, "created_from=2026-13-45")
    assert excinfo.value.code == "invalid_range"


def test_combined_filters_and_pagination(service):
    """SPEC-ORD-024：组合筛选后 total 为过滤后的总数，分页在结果集上生效。"""
    _, first = handle_get_orders(
        service,
        "status=paid&created_from=2026-03-10&created_to=2026-03-31&page_size=1",
    )
    assert first["total"] == 2
    assert len(first["items"]) == 1
    assert first["items"][0]["id"] == "ORD-1014"

    _, second = handle_get_orders(
        service,
        "status=paid&created_from=2026-03-10&created_to=2026-03-31&page_size=1&page=2",
    )
    assert second["total"] == 2
    assert [item["id"] for item in second["items"]] == ["ORD-1011"]


def test_filtered_result_keeps_desc_order(service):
    """SPEC-ORD-030：筛选不改变排序契约。"""
    _, payload = handle_get_orders(service, "status=paid&page_size=100")
    timestamps = [item["created_at"] for item in payload["items"]]
    assert timestamps == sorted(timestamps, reverse=True)


def test_no_filter_behaviour_unchanged(service):
    """SPEC-ORD-030：不带新参数时行为与修改前一致。"""
    status, payload = handle_get_orders(service, "page_size=100")
    assert status == 200
    assert payload["total"] == 16
    assert payload["items"][0]["id"] == "ORD-1016"


def test_unknown_query_param_still_ignored(service):
    """SPEC-ORD-030：未知查询参数继续被忽略，不报错。"""
    status, payload = handle_get_orders(service, "bogus=1&page_size=100")
    assert status == 200
    assert payload["total"] == 16
