"""Knowledge point extraction from the chunk metadata already in seekdb.

A knowledge point is a document section, not a hand-written taxonomy: every
``section`` returned by the chunker becomes one point, and every chunk under
that section is linked back to it. That keeps the practice queue traceable to
real source text and avoids maintaining a second, divergent knowledge graph.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from ..seekdb import db, repo
from ..trace.models import LAYER_SEEKDB, TraceEvent


def _kp_id(subject: str, section: str) -> str:
    digest = hashlib.sha1(f"{subject}|{section}".encode("utf-8")).hexdigest()
    return f"kp-{digest[:16]}"


def _label(section: str) -> str:
    return (section.split(" / ")[-1] or section).strip()


def _iter_metadata(batch: int = 200):
    offset = 0
    while True:
        result = db.collection().get(include=["metadatas"], limit=batch, offset=offset)
        ids = result.get("ids") or []
        if not ids:
            return
        yield from zip(ids, result.get("metadatas") or [])
        if len(ids) < batch:
            return
        offset += len(ids)


def rebuild(session_id: str = "system") -> dict:
    """Recompute the knowledge-point map from all indexed chunks."""
    groups: dict[tuple[str, str], list[str]] = {}
    for chunk_id, metadata in _iter_metadata():
        subject = (metadata.get("subject") or "未分类").strip()
        section = (metadata.get("section") or "正文").strip()
        groups.setdefault((subject, section), []).append(chunk_id)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    points: list[dict] = []
    links: list[tuple[str, str, float]] = []
    for (subject, section), chunk_ids in groups.items():
        kp_id = _kp_id(subject, section)
        points.append(
            {
                "kp_id": kp_id,
                "name": _label(section),
                "subject": subject,
                "description": section,
                "created_at": now,
            }
        )
        links.extend((kp_id, chunk_id, 1.0) for chunk_id in chunk_ids)

    for point in points:
        repo.upsert_knowledge_point(point)
    repo.replace_all_kp_links(links)

    event = TraceEvent(
        session_id=session_id,
        layer=LAYER_SEEKDB,
        operation="knowledge_rebuild",
        input_text=f"{len(points)} sections",
        result_count=len(points),
        summary=f"从 {len(links)} 个 chunk 重建 {len(points)} 个知识点",
        payload={
            "points": [
                {"kp_id": point["kp_id"], "name": point["name"], "subject": point["subject"]}
                for point in points[:20]
            ],
            "links": len(links),
        },
    )
    repo.save_trace(event)
    return {
        "knowledge_points": len(points),
        "links": len(links),
        "trace_id": event.trace_id,
    }
