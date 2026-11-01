"""Memory operations and the trace contract around them.

PowerContext owns the durable memory; this module owns the policy:

* one project scope, resolved or created once per process;
* five kinds, filtered after recall because PowerContext search has no kind
  filter;
* every read and write produces a ``study_traces`` row, including failures, so
  the UI never has to guess whether memory was really used.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Iterable

from ..config import settings
from ..seekdb import repo
from ..trace.models import LAYER_POWERCONTEXT, TraceEvent
from .client import PowerContextClient, PowerContextError
from .kinds import KIND_LABELS, MemoryKind, normalize_kind

MAX_SUMMARY_CHARS = 120
MAX_CONTEXT_MEMORIES = 8

_client: PowerContextClient | None = None
_scope_id: str | None = settings.powercontext_scope_id or None
_scope_lock = threading.Lock()


def client() -> PowerContextClient:
    global _client
    if _client is None:
        _client = PowerContextClient(settings.powercontext_url)
    return _client


def reset_client() -> None:
    global _client, _scope_id
    client_ = _client
    _client = None
    _scope_id = settings.powercontext_scope_id or None
    if client_ is not None:
        client_.close()


def _scope_title() -> str:
    return f"StudyCoach · {settings.user_id}"


def scope_id() -> str:
    """Resolve the project scope, creating it once if it does not exist."""
    global _scope_id
    with _scope_lock:
        if _scope_id:
            return _scope_id
        api = client()
        for scope in api.list_scopes():
            if scope.get("title") == _scope_title():
                _scope_id = scope["scope_id"]
                return _scope_id
        try:
            created = api.create_scope(
                _scope_title(),
                "个人学习教练：学习偏好、薄弱点、会话摘要、计划与任务进展。",
                f"studycoach-{settings.user_id}-scope-v1",
            )
            _scope_id = created["scope_id"]
        except PowerContextError as error:
            # A concurrent start may have created the same idempotency key.
            for scope in api.list_scopes():
                if scope.get("title") == _scope_title():
                    _scope_id = scope["scope_id"]
                    return _scope_id
            raise error
        return _scope_id


def _trace(
    session_id: str,
    operation: str,
    input_text: str,
    result_count: int,
    summary: str,
    payload: dict[str, Any],
) -> str:
    event = TraceEvent(
        session_id=session_id,
        layer=LAYER_POWERCONTEXT,
        operation=operation,
        input_text=input_text[:500],
        result_count=result_count,
        summary=summary,
        payload=payload,
    )
    repo.save_trace(event)
    return event.trace_id


def _entry(row: dict, *, score: float | None = None, matched_by: Iterable[str] = ()) -> dict:
    return {
        "kind": row.get("kind") or "unknown",
        "kind_label": KIND_LABELS.get(_as_kind(row.get("kind")), "其他"),
        "text": row.get("text", ""),
        "artifact_id": (row.get("artifact") or {}).get("artifact_id"),
        "state": row.get("state"),
        "state_version": row.get("state_version"),
        "score": score,
        "matched_by": list(matched_by),
    }


def _as_kind(value: str | None) -> MemoryKind | None:
    try:
        return normalize_kind(value or "")
    except ValueError:
        return None


def write_memory(
    kind: str | MemoryKind,
    text: str,
    *,
    session_id: str = "memory",
    reason: str | None = None,
) -> dict:
    resolved = normalize_kind(kind) if not isinstance(kind, MemoryKind) else kind
    clean = text.strip()
    if not clean:
        raise ValueError("memory text must not be empty")
    try:
        result = client().remember(scope_id(), resolved.value, clean, reason)
        records = result.get("records") or []
        record = records[0] if records else {}
        entry = _entry(record)
        entry["kind"] = resolved.value
        entry["kind_label"] = KIND_LABELS[resolved]
        trace_id = _trace(
            session_id,
            f"remember:{resolved.value}",
            clean,
            1 if result.get("changed") else 0,
            f"写入{entry['kind_label']}：{clean[:MAX_SUMMARY_CHARS]}",
            {
                "scope_id": scope_id(),
                "kind": resolved.value,
                "artifact_id": entry["artifact_id"],
                "state_version": record.get("state_version"),
                "changed": bool(result.get("changed")),
                "reason": reason,
            },
        )
        entry["trace_id"] = trace_id
        return entry
    except PowerContextError as error:
        _trace(
            session_id,
            f"remember:{resolved.value}",
            clean,
            0,
            f"写入失败：{error}",
            {"scope_id": _scope_id, "kind": resolved.value, "error": str(error)},
        )
        raise


def _search(
    query: str,
    *,
    mode: str,
    limit: int,
) -> tuple[str, list[dict]]:
    api = client()
    try:
        payload = api.search(scope_id(), query, mode=mode, limit=limit)
    except PowerContextError as error:
        # A deployment without an embedding provider rejects vector/hybrid.
        # Falling back to lexical recall is a real, visible degradation.
        if mode == "hybrid" and error.status_code in (500, 503):
            payload = api.search(scope_id(), query, mode="fts", limit=limit)
            report_mode = "fts_fallback"
        else:
            raise
    else:
        report_mode = mode
    hits = []
    for hit in payload.get("hits", []):
        entry = _entry(hit.get("memory") or {}, score=hit.get("score"), matched_by=hit.get("matched_by") or ())
        hits.append(entry)
    return report_mode, hits


def recall_memory(
    query: str,
    *,
    kinds: Iterable[str | MemoryKind] | None = None,
    top_k: int = MAX_CONTEXT_MEMORIES,
    session_id: str = "memory",
) -> list[dict]:
    """Semantic recall, filtered to the requested kinds in the app layer."""
    wanted = {normalize_kind(kind).value if not isinstance(kind, MemoryKind) else kind.value for kind in kinds} if kinds else None
    try:
        report_mode, hits = _search(query, mode="hybrid", limit=max(top_k * 3, top_k))
        selected = [hit for hit in hits if wanted is None or hit["kind"] in wanted][:top_k]
        counts: dict[str, int] = {}
        for hit in selected:
            counts[hit["kind"]] = counts.get(hit["kind"], 0) + 1
        _trace(
            session_id,
            "search_memory",
            query,
            len(selected),
            f"{report_mode} 召回 {len(selected)} 条：" + (
                "，".join(f"{kind}×{count}" for kind, count in counts.items()) or "无命中"
            ),
            {
                "scope_id": scope_id(),
                "mode": report_mode,
                "requested_kinds": sorted(wanted) if wanted else "all",
                "hits": [
                    {
                        "artifact_id": hit["artifact_id"],
                        "kind": hit["kind"],
                        "score": hit["score"],
                        "matched_by": hit["matched_by"],
                        "text": hit["text"][:MAX_SUMMARY_CHARS],
                    }
                    for hit in selected
                ],
            },
        )
        return selected
    except PowerContextError as error:
        _trace(
            session_id,
            "search_memory",
            query,
            0,
            f"召回失败：{error}",
            {"scope_id": _scope_id, "error": str(error)},
        )
        raise


def list_memories(
    *,
    limit: int = 50,
    session_id: str = "memory",
    kinds: Iterable[str | MemoryKind] | None = None,
) -> list[dict]:
    wanted = {normalize_kind(kind).value if not isinstance(kind, MemoryKind) else kind.value for kind in kinds} if kinds else None
    try:
        payload = client().list_entries(scope_id(), limit=limit)
        rows = [_entry(row) for row in payload.get("entries", [])]
        if wanted is not None:
            rows = [row for row in rows if row["kind"] in wanted]
        _trace(
            session_id,
            "list_memory",
            f"limit={limit}",
            len(rows),
            f"列出 {len(rows)} 条记忆",
            {"scope_id": scope_id(), "kinds": sorted({row["kind"] for row in rows})},
        )
        return rows
    except PowerContextError as error:
        _trace(
            session_id,
            "list_memory",
            f"limit={limit}",
            0,
            f"读取失败：{error}",
            {"scope_id": _scope_id, "error": str(error)},
        )
        raise


def build_memory_context(
    topic: str,
    *,
    session_id: str = "memory",
    top_k: int = MAX_CONTEXT_MEMORIES,
) -> dict:
    """Recall relevant memories plus the stable profile, then render a prompt block.

    Semantic recall can miss a preference that shares no vocabulary with the
    question, so a small recent-entry pass guarantees the profile and plan are
    considered. Both reads are traced separately.
    """
    recalled = recall_memory(topic, top_k=top_k, session_id=session_id)
    seen = {hit["artifact_id"] for hit in recalled}
    stable_kinds = {MemoryKind.PROFILE.value, MemoryKind.PLAN.value, MemoryKind.TASK_STATE.value}
    try:
        recent = list_memories(limit=30, session_id=session_id, kinds=stable_kinds)
    except PowerContextError:
        recent = []
    for row in recent:
        if row["artifact_id"] in seen:
            continue
        recalled.append(row)
        seen.add(row["artifact_id"])
        if len(recalled) >= top_k + 2:
            break

    order = {kind.value: index for index, kind in enumerate(MemoryKind)}
    recalled.sort(key=lambda row: (order.get(row["kind"], 99), -(row.get("score") or 0.0)))
    lines = [
        f"[{row['kind']}] {row['text']}"
        for row in recalled
        if row["text"].strip()
    ]
    block = ""
    if lines:
        block = (
            "以下是 PowerContext 中关于这位学习者的长期记忆。"
            "回答时自然使用，不要逐条复述，也不要把记忆当成教材证据：\n"
            "<<<MEMORY_CONTEXT>>>\n"
            + "\n".join(lines)
            + "\n<<<END_MEMORY_CONTEXT>>>"
        )
    counts: dict[str, int] = {}
    for row in recalled:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    trace_id = _trace(
        session_id,
        "build_context",
        topic,
        len(recalled),
        "注入 " + (", ".join(f"{kind}×{count}" for kind, count in counts.items()) or "0 条记忆"),
        {
            "scope_id": scope_id(),
            "artifact_ids": [row["artifact_id"] for row in recalled],
            "kinds": counts,
        },
    )
    return {
        "block": block,
        "memories": recalled,
        "counts": counts,
        "scope_id": scope_id(),
        "trace_id": trace_id,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def probe() -> dict:
    """Readiness only; used by /health without touching memory entries."""
    try:
        readiness = client().ready()
        return {
            "url": settings.powercontext_url,
            "ready": readiness.get("status") == "ready",
            "checks": readiness.get("checks", {}),
        }
    except PowerContextError as error:
        return {"url": settings.powercontext_url, "ready": False, "error": str(error)}


def status() -> dict:
    """Integration status plus memory counts for the UI footer/panel."""
    api = client()
    info: dict[str, Any] = {"url": settings.powercontext_url}
    try:
        readiness = api.ready()
        info["ready"] = readiness.get("status") == "ready"
        info["checks"] = readiness.get("checks", {})
        info["scope_id"] = scope_id()
        info["scope_title"] = _scope_title()
        entries = api.list_entries(info["scope_id"], limit=100).get("entries", [])
        counts: dict[str, int] = {}
        for row in entries:
            counts[row.get("kind", "unknown")] = counts.get(row.get("kind", "unknown"), 0) + 1
        info["memories"] = len(entries)
        info["kinds"] = counts
        info["version"] = api.server_info().get("package_version")
        _trace(
            "status",
            "list_memory",
            "status panel",
            len(entries),
            f"记忆状态：{len(entries)} 条",
            {"scope_id": info["scope_id"], "kinds": counts},
        )
    except PowerContextError as error:
        info["ready"] = False
        info["error"] = str(error)
    return info
