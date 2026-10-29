"""回归：真实 HTTP 层可用性。

确认业务工程可以真正启动并通过 socket 提供服务，避免出现"只能在进程内调用"的假可用。
"""

from __future__ import annotations

import json
import threading
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from orderhub.api import create_server
from orderhub.app import build_service


@pytest.fixture()
def live_server():
    server = create_server(build_service(), host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_list_orders(live_server):
    with urlopen(f"{live_server}/orders?page_size=3", timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    assert response.status == 200
    assert payload["total"] == 16
    assert len(payload["items"]) == 3


def test_http_error_payload_shape(live_server):
    with pytest.raises(HTTPError) as excinfo:
        urlopen(f"{live_server}/orders?page_size=0", timeout=5)
    assert excinfo.value.code == 400
    body = json.loads(excinfo.value.read().decode("utf-8"))
    assert body["error"] == "invalid_page_size"
    assert "detail" in body
