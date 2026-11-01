"""Thin HTTP client for the PowerContext server.

Only the endpoints StudyCoach actually uses are wrapped. Every failure is
raised as ``PowerContextError`` with the operation name so the caller can write
an honest trace instead of silently degrading to a fabricated result.
"""

from __future__ import annotations

from typing import Any

import httpx


class PowerContextError(RuntimeError):
    def __init__(self, operation: str, message: str, status_code: int | None = None) -> None:
        self.operation = operation
        self.status_code = status_code
        super().__init__(f"PowerContext {operation} failed: {message}")


class PowerContextClient:
    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def _request(self, operation: str, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            raise PowerContextError(operation, f"{type(error).__name__}: {error}") from error
        if response.status_code >= 400:
            body = response.text.strip().replace("\n", " ")[:300]
            raise PowerContextError(operation, body or response.reason_phrase, response.status_code)
        if not response.content:
            return None
        return response.json()

    def ready(self) -> dict:
        return self._request("ready", "GET", "/health/ready")

    def server_info(self) -> dict:
        return self._request("server_info", "GET", "/v1/server-info")

    def list_scopes(self) -> list[dict]:
        payload = self._request("list_scopes", "GET", "/v1/scopes")
        return payload.get("items", [])

    def create_scope(self, title: str, summary: str, idempotency_key: str) -> dict:
        return self._request(
            "create_scope",
            "POST",
            "/v1/scopes",
            json={"title": title, "summary": summary, "idempotency_key": idempotency_key},
        )

    def remember(self, scope_id: str, kind: str, text: str, reason: str | None = None) -> dict:
        return self._request(
            "remember",
            "POST",
            "/v1/memory/remember",
            json={"scope_id": scope_id, "kind": kind, "text": text, "reason": reason},
        )

    def search(
        self,
        scope_id: str,
        query: str,
        *,
        mode: str = "hybrid",
        limit: int = 10,
    ) -> dict:
        return self._request(
            "search",
            "POST",
            "/v1/memory/search",
            json={"scope_id": scope_id, "query": query, "mode": mode, "limit": limit},
        )

    def list_entries(
        self,
        scope_id: str,
        *,
        limit: int = 50,
        include_inactive: bool = False,
        cursor: str | None = None,
    ) -> dict:
        return self._request(
            "list_entries",
            "POST",
            "/v1/memory/entries/list",
            json={
                "scope_id": scope_id,
                "limit": limit,
                "include_inactive": include_inactive,
                "cursor": cursor,
            },
        )

    def close(self) -> None:
        self._client.close()
