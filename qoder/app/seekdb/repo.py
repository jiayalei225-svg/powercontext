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


def start_session(session_id: str, user_id: str, topic: str | None = None) -> None:
    db.execute(
        """
        INSERT IGNORE INTO study_sessions (session_id, user_id, topic, started_at)
        VALUES (%s, %s, %s, UTC_TIMESTAMP(6))
        """,
        (session_id, user_id, topic),
    )


def set_session_topic(session_id: str, topic: str) -> None:
    db.execute(
        "UPDATE study_sessions SET topic=%s WHERE session_id=%s AND (topic IS NULL OR topic='')",
        (topic[:255], session_id),
    )


def end_session(session_id: str) -> None:
    db.execute("UPDATE study_sessions SET ended_at=UTC_TIMESTAMP(6) WHERE session_id=%s", (session_id,))


def get_session(session_id: str) -> dict | None:
    row = db.query_one("SELECT * FROM study_sessions WHERE session_id=%s", (session_id,))
    return iso(row) if row else None


def session_evidence(session_id: str) -> dict:
    """Aggregate seekdb trace payloads into topics for the session summary."""
    rows = db.query_all(
        """
        SELECT input_text, payload_json FROM study_traces
        WHERE session_id=%s AND layer='seekdb' AND operation LIKE 'search_%%'
        ORDER BY ts ASC
        """,
        (session_id,),
    )
    sections: list[str] = []
    titles: list[str] = []
    queries: list[str] = []
    seen_queries: set[str] = set()
    for row in rows:
        query = (row.get("input_text") or "").strip()
        # /api/search and /api/ask record the same question, differing only by
        # terminal punctuation; dedupe on the normalized form.
        key = query.rstrip("。？！?!；;，, ")
        if key and key not in seen_queries:
            seen_queries.add(key)
            queries.append(query)
        try:
            payload = json.loads(row.get("payload_json") or "{}")
        except ValueError:
            continue
        for hit in payload.get("hits", []):
            section = hit.get("section")
            title = hit.get("doc_title")
            if section and section not in sections:
                sections.append(section)
            if title and title not in titles:
                titles.append(title)
    return {
        "sections": sections[:8],
        "doc_titles": titles[:6],
        "queries": queries[:6],
        "searches": len(rows),
    }


def trace_counts(session_id: str) -> dict:
    rows = db.query_all(
        "SELECT layer, COUNT(*) AS n FROM study_traces WHERE session_id=%s GROUP BY layer",
        (session_id,),
    )
    return {row["layer"]: int(row["n"]) for row in rows}


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


# ---------------------------------------------------------------------------
# Knowledge points, questions and mastery
# ---------------------------------------------------------------------------


def upsert_knowledge_point(record: dict) -> None:
    db.execute(
        """
        INSERT INTO study_knowledge_points (kp_id, name, subject, description, created_at)
        VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            name=VALUES(name), subject=VALUES(subject), description=VALUES(description)
        """,
        (
            record["kp_id"],
            record["name"][:255],
            record["subject"][:64],
            record.get("description") or "",
            record["created_at"],
        ),
    )


def replace_all_kp_links(links: list[tuple[str, str, float]]) -> None:
    """Rebuild the many-to-many map in one connection.

    Knowledge points are derived data: chunk text and metadata stay in the
    collection, while this table only answers "which chunks teach this point".
    Deleting and reinserting the whole map is cheaper and safer than tracking
    per-document deltas, and mastery rows are untouched.
    """
    with db.sql() as cursor:
        cursor.execute("DELETE FROM study_kp_chunks")
        if links:
            cursor.executemany(
                "INSERT INTO study_kp_chunks (kp_id, chunk_id, weight) VALUES (%s, %s, %s)",
                links,
            )


def list_knowledge_points(subject: str | None = None) -> list[dict]:
    params: list[Any] = []
    clause = ""
    if subject:
        clause = "AND kp.subject=%s"
        params.append(subject)
    rows = db.query_all(
        f"""
        SELECT kp.*,
               (SELECT COUNT(*) FROM study_kp_chunks kc WHERE kc.kp_id=kp.kp_id) AS chunk_count,
               m.score, m.ease, m.interval_days, m.repetitions, m.lapses,
               m.last_practiced_at, m.next_review_at
        FROM study_knowledge_points kp
        LEFT JOIN study_mastery m ON m.kp_id=kp.kp_id
        WHERE EXISTS (SELECT 1 FROM study_kp_chunks kc2 WHERE kc2.kp_id=kp.kp_id)
        {clause}
        ORDER BY kp.subject ASC, kp.name ASC
        """,
        tuple(params),
    )
    return [iso(row) for row in rows]


def chunk_ids_for_kps(kp_ids: list[str]) -> dict[str, list[str]]:
    if not kp_ids:
        return {}
    placeholders = ",".join(["%s"] * len(kp_ids))
    rows = db.query_all(
        f"""
        SELECT kp_id, chunk_id, weight FROM study_kp_chunks
        WHERE kp_id IN ({placeholders})
        ORDER BY kp_id ASC, weight DESC, chunk_id ASC
        """,
        tuple(kp_ids),
    )
    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(row["kp_id"], []).append(row["chunk_id"])
    return result


def review_queue(subject: str | None = None, limit: int = 20) -> list[dict]:
    params: list[Any] = []
    clause = ""
    if subject:
        clause = "AND kp.subject=%s"
        params.append(subject)
    params.append(int(limit))
    rows = db.query_all(
        f"""
        SELECT kp.*,
               (SELECT COUNT(*) FROM study_kp_chunks kc WHERE kc.kp_id=kp.kp_id) AS chunk_count,
               m.score, m.ease, m.interval_days, m.repetitions, m.lapses,
               m.last_practiced_at, m.next_review_at
        FROM study_knowledge_points kp
        LEFT JOIN study_mastery m ON m.kp_id=kp.kp_id
        WHERE EXISTS (SELECT 1 FROM study_kp_chunks kc2 WHERE kc2.kp_id=kp.kp_id)
          AND (m.kp_id IS NULL OR m.next_review_at IS NULL OR m.next_review_at <= UTC_TIMESTAMP(6))
          {clause}
        ORDER BY (m.kp_id IS NOT NULL) ASC,
                 COALESCE(m.score, 0.5) ASC,
                 m.next_review_at ASC,
                 kp.name ASC
        LIMIT %s
        """,
        tuple(params),
    )
    return [iso(row) for row in rows]


def review_stats(subject: str | None = None) -> dict:
    params: tuple = (subject,) if subject else ()
    subject_clause = "AND kp.subject=%s" if subject else ""
    base = f"""
        FROM study_knowledge_points kp
        LEFT JOIN study_mastery m ON m.kp_id=kp.kp_id
        WHERE EXISTS (SELECT 1 FROM study_kp_chunks kc WHERE kc.kp_id=kp.kp_id)
        {subject_clause}
    """
    total = db.query_one(f"SELECT COUNT(*) AS n {base}", params) or {"n": 0}
    due = db.query_one(
        f"SELECT COUNT(*) AS n {base} AND (m.kp_id IS NULL OR m.next_review_at IS NULL OR m.next_review_at <= UTC_TIMESTAMP(6))",
        params,
    ) or {"n": 0}
    new = db.query_one(f"SELECT COUNT(*) AS n {base} AND m.kp_id IS NULL", params) or {"n": 0}
    weak = db.query_one(f"SELECT COUNT(*) AS n {base} AND m.score < 0.45", params) or {"n": 0}
    average = db.query_one(
        f"SELECT AVG(COALESCE(m.score, 0.5)) AS v {base}", params
    ) or {"v": 0.5}
    practice = db.query_one(
        """
        SELECT COUNT(*) AS answers,
               COUNT(DISTINCT kp_id) AS points,
               COALESCE(SUM(is_correct), 0) AS correct
        FROM study_practice_records
        WHERE created_at >= UTC_DATE()
        """
    ) or {"answers": 0, "points": 0, "correct": 0}
    return {
        "total": int(total["n"]),
        "due": int(due["n"]),
        "new": int(new["n"]),
        "weak": int(weak["n"]),
        "average": round(float(average["v"] or 0.5), 4),
        "answered_today": int(practice["answers"]),
        "practiced_today": int(practice["points"]),
        "correct_today": int(practice["correct"]),
    }


def get_mastery(kp_id: str) -> dict | None:
    return db.query_one("SELECT * FROM study_mastery WHERE kp_id=%s", (kp_id,))


def upsert_mastery(record: dict) -> None:
    db.execute(
        """
        INSERT INTO study_mastery
            (kp_id, score, ease, interval_days, repetitions, lapses,
             last_practiced_at, next_review_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            score=VALUES(score), ease=VALUES(ease), interval_days=VALUES(interval_days),
            repetitions=VALUES(repetitions), lapses=VALUES(lapses),
            last_practiced_at=VALUES(last_practiced_at),
            next_review_at=VALUES(next_review_at), updated_at=VALUES(updated_at)
        """,
        (
            record["kp_id"],
            record["score"],
            record["ease"],
            int(record["interval_days"]),
            int(record["repetitions"]),
            int(record["lapses"]),
            record["last_practiced_at"],
            record["next_review_at"],
            record["updated_at"],
        ),
    )


def insert_practice_record(record: dict) -> None:
    db.execute(
        """
        INSERT INTO study_practice_records
            (record_id, session_id, kp_id, question_id, is_correct, answer_text, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            record["record_id"],
            record["session_id"],
            record["kp_id"],
            record["question_id"],
            1 if record["is_correct"] else 0,
            record.get("answer_text") or "",
            record["created_at"],
        ),
    )


def upsert_question(record: dict) -> None:
    db.execute(
        """
        INSERT INTO study_questions
            (question_id, kp_id, question_type, prompt_text, options_json,
             answer, explanation, source_chunk_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            kp_id=VALUES(kp_id), question_type=VALUES(question_type),
            prompt_text=VALUES(prompt_text), options_json=VALUES(options_json),
            answer=VALUES(answer), explanation=VALUES(explanation),
            source_chunk_id=VALUES(source_chunk_id)
        """,
        (
            record["question_id"],
            record["kp_id"],
            record["question_type"],
            record["prompt_text"],
            record["options_json"],
            record["answer"],
            record.get("explanation") or "",
            record.get("source_chunk_id"),
        ),
    )


def questions_by_ids(question_ids: list[str]) -> dict[str, dict]:
    if not question_ids:
        return {}
    placeholders = ",".join(["%s"] * len(question_ids))
    rows = db.query_all(
        f"""
        SELECT q.*, kp.name AS kp_name, kp.subject AS kp_subject
        FROM study_questions q
        LEFT JOIN study_knowledge_points kp ON kp.kp_id=q.kp_id
        WHERE q.question_id IN ({placeholders})
        """,
        tuple(question_ids),
    )
    return {row["question_id"]: row for row in rows}

