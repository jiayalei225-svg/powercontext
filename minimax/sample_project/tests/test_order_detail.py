"""回归：单条查询、健康检查与仓储基础行为。"""

from __future__ import annotations

import pytest

from orderhub.api import dispatch, handle_get_order
from orderhub.app import build_service
from orderhub.errors import ApiError
from orderhub.repository import OrderNotFoundError, OrderRepository


@pytest.fixture()
def service():
    return build_service()


def test_get_existing_order(service):
    status, payload = handle_get_order(service, "ORD-1001")
    assert status == 200
    assert payload["id"] == "ORD-1001"
    assert payload["status"] == "paid"
    assert payload["total_cents"] == 128000


def test_get_missing_order_returns_404(service):
    with pytest.raises(ApiError) as excinfo:
        handle_get_order(service, "ORD-9999")
    assert excinfo.value.code == "order_not_found"
    assert excinfo.value.status == 404


def test_health_endpoint(service):
    status, payload = dispatch(service, "/health", "")
    assert status == 200
    assert payload == {"status": "ok"}


def test_unknown_path_returns_404(service):
    with pytest.raises(ApiError) as excinfo:
        dispatch(service, "/nope", "")
    assert excinfo.value.code == "not_found"
    assert excinfo.value.status == 404


def test_repository_count_and_get(service):
    repository = OrderRepository.from_json_file(
        build_service.__globals__["DATA_FILE"]
    )
    assert repository.count() == 16
    with pytest.raises(OrderNotFoundError):
        repository.get("ORD-0000")
