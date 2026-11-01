"""Relational access for documents and traces.

All writes go through parameterized SQL against the embedded seekdb instance.
The collection holds chunk text/vectors; this module only owns the tables that
benefit from SQL (counts, ordering, aggregation).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from . import db


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(value: Any) -> Any:
    """Serialize datetimes for JSON while keeping other values untouched."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).isoformat(timespec="seconds")
    if isinstance(value, dict):
        return {k: iso(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [iso(v) for v in value]
    return value


def upsert_document(record: dict) -> None:
    db.execute(
        """
        INSERT INTO study_documents
            (doc_id, title, subject, source_path, file_type, page_count,
             chunk_count, content_hash, imported_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            title=VALUES(title), subject=VALUES(subject), source_path=VALUES(source_path),
            file_type=VALUES(file_type), page_count=VALUES(page_count),
            chunk_count=VALUES(chunk_count), content_hash=VALUES(content_hash),
            imported_at=VALUES(imported_at)
        """,
        (
            record["doc_id"],
            record["title"],
            record["subject"],
            record["source_path"],
            record["file_type"],
            int(record.get("page_count") or 0),
            int(record.get("chunk_count") or 0),
            record["content_hash"],
            record["imported_at"],
        ),
    )


def get_document(doc_id: str) -> dict | None:
    row = db.query_one("SELECT * FROM study_documents WHERE doc_id=%s", (doc_id,))
    return iso(row) if row else None


def list_documents() -> list[dict]:
    rows = db.query_all("SELECT * FROM study_documents ORDER BY imported_at DESC, title ASC")
    return [iso(row) for row in rows]


def delete_document_row(doc_id: str) -> None:
    db.execute("DELETE FROM study_documents WHERE doc_id=%s", (doc_id,))


def save_trace(event: Any) -> None:
    db.execute(
        """
        INSERT INTO study_traces
            (trace_id, session_id, ts, layer, operation, input_text,
             result_count, summary, payload_json)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        event.to_row(),
    )


def list_traces(session_id: str | None = None, limit: int = 60) -> list[dict]:
    if session_id:
        rows = db.query_all(
            "SELECT * FROM study_traces WHERE session_id=%s ORDER BY ts DESC LIMIT %s",
            (session_id, int(limit)),
        )
    else:
        rows = db.query_all("SELECT * FROM study_traces ORDER BY ts DESC LIMIT %s", (int(limit),))
    out = []
    for row in rows:
        payload = {}
        if row.get("payload_json"):
            try:
                payload = json.loads(row["payload_json"])
            except ValueError:
                payload = {"raw": row["payload_json"]}
        out.append(
            {
                "trace_id": row["trace_id"],
                "session_id": row["session_id"],
                "ts": iso(row["ts"]),
                "layer": row["layer"],
                "operation": row["operation"],
                "input": row["input_text"],
                "result_count": row["result_count"],
                "summary": row["summary"],
                "payload": payload,
            }
        )
    return out
