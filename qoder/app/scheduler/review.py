"""The "today" view: due points, aggregate mastery and the trace behind them."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..seekdb import repo
from ..trace.models import LAYER_SEEKDB, TraceEvent
from .mastery import describe_next


def _decorate(row: dict[str, Any]) -> dict[str, Any]:
    next_review = row.get("next_review_at")
    if row.get("kp_id") is None or row.get("score") is None:
        state = "new"
    elif next_review is None:
        state = "new"
    else:
        state = "due"
    score = row.get("score")
    return {
        "kp_id": row["kp_id"],
        "name": row["name"],
        "subject": row["subject"],
        "section": row.get("description") or row["name"],
        "chunk_count": int(row.get("chunk_count") or 0),
        "score": round(float(score), 4) if score is not None else None,
        "state": state,
        "next_review_at": next_review,
        "next_review_label": describe_next(next_review),
        "last_practiced_at": row.get("last_practiced_at"),
        "repetitions": int(row.get("repetitions") or 0),
        "lapses": int(row.get("lapses") or 0),
        "interval_days": int(row.get("interval_days") or 0),
    }


def today(subject: str | None = None, limit: int = 12, session_id: str = "review") -> dict:
    queue = [_decorate(row) for row in repo.review_queue(subject, limit)]
    stats = repo.review_stats(subject)
    event = TraceEvent(
        session_id=session_id,
        layer=LAYER_SEEKDB,
        operation="review_today",
        input_text=subject or "全部学科",
        result_count=len(queue),
        summary=f"今日队列 {stats['due']} 个（新 {stats['new']}，薄弱 {stats['weak']}）",
        payload={"stats": stats, "queue": [item["kp_id"] for item in queue]},
    )
    repo.save_trace(event)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stats": stats,
        "queue": queue,
        "trace_id": event.trace_id,
    }
