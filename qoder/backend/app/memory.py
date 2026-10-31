"""PowerContext memory: what this user prefers, kept across sessions.

Preferences are stored as one versioned JSON payload inside a Memory entry, so
the assistant can re-apply them deterministically instead of re-reading a
transcript. Every search is also journaled as progress memory.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import httpx

from .config import settings

PREF_MARK = "paperdesk.prefs.v1|"
SEARCH_MARK = "paperdesk.search.v1|"

# One pooled client: opening a fresh TCP connection to the local memory
# service costs ~1.5 s on Windows, which used to dominate every search.
_client: httpx.Client | None = None
_client_lock = threading.Lock()

_health_cache: tuple[float, bool] | None = None
_prefs_cache: tuple[float, dict] | None = None
_HEALTH_TTL = 5.0
_PREFS_TTL = 10.0


class MemoryError(RuntimeError):
    pass


def _get_client() -> httpx.Client:
    global _client
    with _client_lock:
        if _client is None or _client.is_closed:
            _client = httpx.Client(timeout=settings.powercontext_timeout)
        return _client


def _call(path: str, payload: dict | None = None, method: str = "POST") -> Any:
    url = f"{settings.powercontext_url}{path}"
    try:
        response = _get_client().request(method, url, json=payload)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise MemoryError(f"PowerContext 不可用: {exc}") from exc


def available() -> bool:
    global _health_cache
    if not settings.memory_enabled:
        return False
    now = time.monotonic()
    if _health_cache and now - _health_cache[0] < _HEALTH_TTL:
        return _health_cache[1]
    try:
        _call("/health/ready", method="GET")
        _health_cache = (now, True)
        return True
    except MemoryError:
        _health_cache = (now, False)
        return False


_scope_cache: dict[str, str] = {}


def scope_id() -> str:
    if "id" not in _scope_cache:
        _scope_cache["id"] = _call("/v1/scopes/default", method="GET")["scope_id"]
    return _scope_cache["id"]


def _remember(kind: str, text: str, reason: str) -> dict:
    return _call(
        "/v1/memory/remember",
        {"scope_id": scope_id(), "kind": kind, "text": text, "reason": reason},
    )


def _entries(limit: int = 100) -> list[dict]:
    data = _call("/v1/memory/entries/list", {"scope_id": scope_id(), "limit": limit})
    return data.get("entries", [])


def _payload(entry: dict, mark: str) -> dict | None:
    text = entry.get("text") or ""
    if not text.startswith(mark):
        return None
    try:
        return json.loads(text[len(mark) :])
    except json.JSONDecodeError:
        return None


def save_preferences(prefs: dict) -> dict:
    global _prefs_cache
    payload = dict(prefs)
    payload["saved_at"] = time.time()
    entry = _remember("preference", PREF_MARK + json.dumps(payload, ensure_ascii=False), "用户在设置面板保存检索偏好")
    _prefs_cache = (time.monotonic(), dict(prefs))
    record = (entry.get("records") or [{}])[0]
    return {"artifact": record.get("artifact"), "preferences": prefs}


def load_preferences() -> dict:
    global _prefs_cache
    now = time.monotonic()
    if _prefs_cache and now - _prefs_cache[0] < _PREFS_TTL:
        return dict(_prefs_cache[1])
    best: dict | None = None
    for entry in _entries():
        payload = _payload(entry, PREF_MARK)
        if payload and (best is None or payload.get("saved_at", 0) > best.get("saved_at", 0)):
            best = payload
    best = dict(best or {})
    best.pop("saved_at", None)
    _prefs_cache = (now, dict(best))
    return best


def log_search(query: str, filters: dict, hits: int) -> None:
    payload = {"query": query, "filters": filters, "hits": hits, "at": time.time()}
    _remember("progress", SEARCH_MARK + json.dumps(payload, ensure_ascii=False), "记录一次检索，用于任务进度与复现")


def recent_searches(limit: int = 10) -> list[dict]:
    items: list[dict] = []
    for entry in _entries():
        payload = _payload(entry, SEARCH_MARK)
        if payload:
            items.append(payload)
    items.sort(key=lambda item: item.get("at", 0), reverse=True)
    return items[:limit]


def snapshot(limit: int = 20) -> dict:
    """Everything the UI needs to prove memory is doing something."""
    if not available():
        return {"connected": False, "scope_id": None, "preferences": {}, "searches": [], "entries": []}
    entries = _entries()
    return {
        "connected": True,
        "scope_id": scope_id(),
        "preferences": load_preferences(),
        "searches": recent_searches(),
        "entries": [
            {
                "artifact_id": (e.get("artifact") or {}).get("artifact_id"),
                "revision": (e.get("artifact") or {}).get("revision"),
                "kind": e.get("kind"),
                "text": e.get("text"),
                "state": e.get("state"),
            }
            for e in entries
            if (e.get("text") or "").startswith((PREF_MARK, SEARCH_MARK))
        ],
    }
