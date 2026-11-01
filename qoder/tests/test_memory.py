from __future__ import annotations

import json

import pytest

from app import memory


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch):
    memory._prefs = None
    monkeypatch.setattr(memory, "scope", lambda: "scp_test")
    yield
    memory._prefs = None


def pref(saved_at: int, **values) -> dict:
    return {"text": memory.PREF_MARK + json.dumps({**values, "saved_at": saved_at})}


def test_entries_walks_every_cursor_page(monkeypatch):
    calls: list[dict] = []

    def fake_call(path, payload=None, method="POST"):
        calls.append(payload or {})
        if "cursor" not in (payload or {}):
            return {"items": [{"text": "a"}], "next_cursor": "cursor-2"}
        return {"items": [{"text": "b"}], "next_cursor": None}

    monkeypatch.setattr(memory, "_call", fake_call)
    found = memory.entries(kind="preference")

    assert [item["text"] for item in found] == ["a", "b"]
    assert calls[0]["kind"] == "preference"
    assert calls[1]["cursor"] == "cursor-2"
    assert all(call["scope_id"] == "scp_test" for call in calls)


def test_latest_preference_is_read_from_second_page(monkeypatch):
    pages = {
        None: {
            "items": [pref(100, year_from=2020), pref(200, venues=["SIGIR"])],
            "next_cursor": "page-2",
        },
        "page-2": {
            "items": [pref(300, year_from=2024, only_with_code=True)],
            "next_cursor": None,
        },
    }
    seen: list[dict] = []

    def fake_call(path, payload=None, method="POST"):
        seen.append(payload or {})
        return pages[payload.get("cursor")]

    monkeypatch.setattr(memory, "_call", fake_call)
    assert memory.load_prefs(fresh=True) == {"year_from": 2024, "only_with_code": True}
    assert len(seen) == 2


def test_snapshot_keeps_preferences_and_old_traces(monkeypatch):
    trace = {
        "text": memory.TRACE_MARK
        + json.dumps({"query": "旧查询", "filters": {}, "hits": 2, "at": 10}),
        "artifact": {"artifact_id": "art_trace", "revision": 1},
        "kind": "progress",
    }
    newest = pref(300, year_from=2024, venues=["ACL"])
    newest["artifact"] = {"artifact_id": "art_pref", "revision": 1}
    newest["kind"] = "preference"

    def fake_call(path, payload=None, method="POST"):
        if payload.get("kind") == "preference":
            return {"items": [newest], "next_cursor": None}
        return {"items": [trace], "next_cursor": None}

    monkeypatch.setattr(memory, "_call", fake_call)
    monkeypatch.setattr(memory, "enabled", lambda: True)
    snap = memory.snapshot()

    assert snap["preferences"] == {"year_from": 2024, "venues": ["ACL"]}
    assert snap["searches"][0]["query"] == "旧查询"
    assert snap["memories"][0]["artifact"] == "art_pref"


def test_missing_preferences_returns_empty(monkeypatch):
    monkeypatch.setattr(
        memory, "_call", lambda path, payload=None, method="POST": {"items": [], "next_cursor": None}
    )
    assert memory.load_prefs(fresh=True) == {}
