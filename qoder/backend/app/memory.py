"""PowerContext client: durable preferences and a search trail."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import httpx

from .settings import settings

PREF_MARK = "paperdesk2/prefs/v1|"
TRACE_MARK = "paperdesk2/trace/v1|"

_client: httpx.Client | None = None
_client_lock = threading.Lock()
_health: tuple[float, bool] | None = None
_prefs: tuple[float, dict] | None = None
_HEALTH_TTL = 4.0
_PREFS_TTL = 12.0


class MemoryError(RuntimeError):
    pass


def _http() -> httpx.Client:
    global _client
    with _client_lock:
        if _client is None or _client.is_closed:
            _client = httpx.Client(timeout=settings.powercontext_timeout)
        return _client


def _call(path: str, payload: dict | None = None, method: str = "POST") -> Any:
    try:
        response = _http().request(method, f"{settings.powercontext_url}{path}", json=payload)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise MemoryError(f"PowerContext 调用失败：{exc}") from exc


def enabled() -> bool:
    global _health
    if not settings.memory_enabled:
        return False
    now = time.monotonic()
    if _health and now - _health[0] < _HEALTH_TTL:
        return _health[1]
    try:
        _call("/health/ready", method="GET")
        _health = (now, True)
    except MemoryError:
        _health = (now, False)
    return _health[1]


_scope: dict[str, str] = {}


def scope() -> str:
    if "id" not in _scope:
        _scope["id"] = _call("/v1/scopes/default", method="GET")["scope_id"]
    return _scope["id"]


def remember(kind: str, text: str, reason: str) -> dict:
    return _call(
        "/v1/memory/remember",
        {"scope_id": scope(), "kind": kind, "text": text, "reason": reason},
    )


def entries(limit: int = 100) -> list[dict]:
    limit = max(1, min(limit, 100))
    data = _call("/v1/memory/entries/list", {"scope_id": scope(), "limit": limit})
    return data.get("entries", [])


def _decode(entry: dict, marker: str) -> dict | None:
    text = entry.get("text") or ""
    if not text.startswith(marker):
        return None
    try:
        return json.loads(text[len(marker) :])
    except json.JSONDecodeError:
        return None


def _pick_prefs(items: list[dict]) -> dict:
    newest: dict | None = None
    for entry in items:
        payload = _decode(entry, PREF_MARK)
        if payload is None:
            continue
        if newest is None or payload.get("saved_at", 0) > newest.get("saved_at", 0):
            newest = payload
    if newest is None:
        return {}
    result = dict(newest)
    result.pop("saved_at", None)
    return result


def save_prefs(prefs: dict) -> dict:
    global _prefs
    payload = dict(prefs)
    payload["saved_at"] = time.time()
    response = remember(
        "preference",
        PREF_MARK + json.dumps(payload, ensure_ascii=False),
        "保存 PaperDesk 检索偏好",
    )
    _prefs = (time.monotonic(), dict(prefs))
    record = (response.get("records") or [{}])[0]
    artifact = record.get("artifact") or {}
    return {
        "preferences": prefs,
        "artifact": artifact.get("artifact_id"),
        "revision": artifact.get("revision"),
    }


def load_prefs() -> dict:
    global _prefs
    now = time.monotonic()
    if _prefs and now - _prefs[0] < _PREFS_TTL:
        return dict(_prefs[1])
    prefs = _pick_prefs(entries())
    _prefs = (now, dict(prefs))
    return prefs


def trace(query: str, filters: dict, hits: int) -> None:
    payload = {"query": query, "filters": filters, "hits": hits, "at": time.time()}
    remember("progress", TRACE_MARK + json.dumps(payload, ensure_ascii=False), "记录一次检索用于复现")


def trail(limit: int = 12) -> list[dict]:
    found = []
    for entry in entries():
        payload = _decode(entry, TRACE_MARK)
        if payload is not None:
            payload["artifact"] = (entry.get("artifact") or {}).get("artifact_id")
            found.append(payload)
    found.sort(key=lambda item: item.get("at", 0), reverse=True)
    return found[:limit]


def snapshot(limit: int = 20) -> dict:
    if not enabled():
        return {
            "connected": False,
            "scope_id": None,
            "preferences": {},
            "searches": [],
            "memories": [],
        }
    items = entries()
    prefs = _pick_prefs(items)
    searches = []
    memories = []
    for entry in items:
        if (entry.get("text") or "").startswith(TRACE_MARK):
            payload = _decode(entry, TRACE_MARK)
            if payload is not None:
                searches.append(payload)
        elif (entry.get("text") or "").startswith(PREF_MARK):
            payload = _decode(entry, PREF_MARK)
            if payload is not None:
                memories.append(
                    {
                        "artifact": (entry.get("artifact") or {}).get("artifact_id"),
                        "revision": (entry.get("artifact") or {}).get("revision"),
                        "kind": entry.get("kind"),
                        "state": entry.get("state"),
                        "saved_at": payload.get("saved_at"),
                        "summary": "检索偏好 · " + _describe(payload),
                    }
                )
    searches.sort(key=lambda item: item.get("at", 0), reverse=True)
    memories.sort(key=lambda item: item.get("saved_at", 0), reverse=True)
    return {
        "connected": True,
        "scope_id": scope(),
        "preferences": load_prefs(),
        "searches": searches[:limit],
        "memories": memories[:limit],
    }


def _describe(prefs: dict) -> str:
    parts = []
    if prefs.get("year_from"):
        parts.append(f"{prefs['year_from']} 年后")
    if prefs.get("venues"):
        parts.append("、".join(prefs["venues"]))
    if prefs.get("only_with_code"):
        parts.append("仅开源")
    if prefs.get("field"):
        parts.append(prefs["field"])
    return " / ".join(parts) if parts else "无默认约束"
