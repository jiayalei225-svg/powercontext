"""Print raw evidence from both systems for review.

Run while StudyCoach is running (the embedded database is already open):

    python scripts/evidence.py

It reads seekdb relational tables directly and asks the PowerContext HTTP API
for the raw memory entries of the StudyCoach scope. Output is intentionally
plain: document ids, chunk counts, mastery rows, trace summaries, memory kind
and text. No formatting beyond JSON so the numbers can be checked by eye.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.memory import service as memory_service  # noqa: E402
from app.memory.client import PowerContextClient  # noqa: E402
from app.seekdb import db  # noqa: E402


def dump(title: str, rows: object) -> None:
    print(f"\n## {title}")
    print(json.dumps(rows, ensure_ascii=False, default=str, indent=2))


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    dump(
        "seekdb · study_documents",
        db.query_all(
            "SELECT doc_id, title, subject, chunk_count, file_type, imported_at "
            "FROM study_documents ORDER BY imported_at"
        ),
    )
    try:
        chunks = db.collection().count()
    except Exception as error:
        chunks = f"unavailable: {type(error).__name__}: {error}"
    dump("seekdb · study_chunks", {"chunks": chunks})

    dump(
        "seekdb · 知识点与掌握度",
        db.query_all(
            """
            SELECT kp.kp_id, kp.name, kp.subject,
                   m.score, m.interval_days, m.repetitions, m.lapses, m.next_review_at
            FROM study_knowledge_points kp
            LEFT JOIN study_mastery m ON m.kp_id = kp.kp_id
            ORDER BY kp.subject, kp.name
            LIMIT 12
            """
        ),
    )
    dump(
        "seekdb · 今日练习",
        db.query_all(
            """
            SELECT record_id, session_id, kp_id, is_correct, answer_text, created_at
            FROM study_practice_records
            WHERE created_at >= UTC_DATE()
            ORDER BY created_at DESC
            LIMIT 10
            """
        ),
    )
    dump(
        "seekdb · 最近轨迹",
        db.query_all(
            "SELECT layer, operation, result_count, summary, ts "
            "FROM study_traces ORDER BY ts DESC LIMIT 12"
        ),
    )
    dump(
        "seekdb · 轨迹分层计数",
        db.query_all("SELECT layer, COUNT(*) AS n FROM study_traces GROUP BY layer"),
    )

    api = PowerContextClient(settings.powercontext_url)
    try:
        scope_id = memory_service.scope_id()
        entries = api.list_entries(scope_id, limit=20).get("entries", [])
    finally:
        api.close()
    slim = [
        {
            "artifact_id": (row.get("artifact") or {}).get("artifact_id"),
            "kind": row.get("kind"),
            "state": row.get("state"),
            "text": row.get("text"),
        }
        for row in entries
    ]
    counts: dict[str, int] = {}
    for row in slim:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    dump("PowerContext · scope", {"scope_id": scope_id, "kinds": counts, "entries": slim})


if __name__ == "__main__":
    main()
