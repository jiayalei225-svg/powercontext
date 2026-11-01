"""seekdb schema: one vector/full-text collection plus relational tables.

Why two shapes in one embedded database:

* ``study_chunks`` is a pyseekdb collection. It owns the text, the embedding,
  the full-text index and the scalar filters used by hybrid retrieval. pyseekdb
  names the physical table ``c$v2$<uuid>``, so it must only be queried through
  the SDK.
* The ``study_*`` tables are plain MySQL-compatible tables created with
  ``pylibseekdb``. Scores, intervals and rankings need SQL aggregation and
  ``ORDER BY``; a collection cannot express that cleanly.

Both live under the same embedded database directory (``SEEKDB_PATH``), and the
two handles are used in one process: pyseekdb for the collection, pylibseekdb
for SQL. This split is intentional and is explained in the README.
"""

from __future__ import annotations

COLLECTION_NAME = "study_chunks"

# Metadata attached to every chunk. These fields are the contract between
# ingest, retrieval and the citation UI; a hit is incomplete without all of them.
CHUNK_METADATA_FIELDS = {
    "chunk_id": "str  - stable id, also used as the collection primary key",
    "doc_id": "str  - document identity",
    "doc_title": "str  - human readable title shown in citations",
    "subject": "str  - subject filter (e.g. machine-learning)",
    "section": "str  - heading path, e.g. '第三章/3.2 正则化'",
    "page": "int  - page number, 0 when the source has no pages",
    "chunk_index": "int  - order inside the document",
    "source_path": "str  - original file path, relative to qoder/",
    "imported_at": "str  - ISO-8601 timestamp",
}

DDL_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS study_documents (
        doc_id        VARCHAR(64)  NOT NULL PRIMARY KEY,
        title         VARCHAR(255) NOT NULL,
        subject       VARCHAR(64)  NOT NULL,
        source_path   VARCHAR(512) NOT NULL,
        file_type     VARCHAR(16)  NOT NULL,
        page_count    INT          NOT NULL DEFAULT 0,
        chunk_count   INT          NOT NULL DEFAULT 0,
        content_hash  VARCHAR(64)  NOT NULL,
        imported_at   DATETIME(6)  NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS study_knowledge_points (
        kp_id       VARCHAR(64)  NOT NULL PRIMARY KEY,
        name        VARCHAR(255) NOT NULL,
        subject     VARCHAR(64)  NOT NULL,
        description TEXT,
        created_at  DATETIME(6)  NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS study_kp_chunks (
        kp_id    VARCHAR(64) NOT NULL,
        chunk_id VARCHAR(128) NOT NULL,
        weight   DOUBLE NOT NULL DEFAULT 1.0,
        PRIMARY KEY (kp_id, chunk_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS study_questions (
        question_id     VARCHAR(64) NOT NULL PRIMARY KEY,
        kp_id           VARCHAR(64) NOT NULL,
        question_type   VARCHAR(32) NOT NULL,
        prompt_text     TEXT        NOT NULL,
        options_json    TEXT,
        answer          TEXT        NOT NULL,
        explanation     TEXT,
        source_chunk_id VARCHAR(128)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS study_practice_records (
        record_id    VARCHAR(64)  NOT NULL PRIMARY KEY,
        session_id   VARCHAR(64)  NOT NULL,
        kp_id        VARCHAR(64)  NOT NULL,
        question_id  VARCHAR(64)  NOT NULL,
        is_correct   TINYINT      NOT NULL,
        answer_text  TEXT,
        created_at   DATETIME(6)  NOT NULL,
        KEY idx_record_kp_time (kp_id, created_at)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS study_mastery (
        kp_id             VARCHAR(64) NOT NULL PRIMARY KEY,
        score             DOUBLE      NOT NULL DEFAULT 0.5,
        ease              DOUBLE      NOT NULL DEFAULT 2.5,
        interval_days     INT         NOT NULL DEFAULT 0,
        repetitions       INT         NOT NULL DEFAULT 0,
        lapses            INT         NOT NULL DEFAULT 0,
        last_practiced_at DATETIME(6),
        next_review_at    DATETIME(6),
        updated_at        DATETIME(6) NOT NULL,
        KEY idx_mastery_next_review (next_review_at),
        KEY idx_mastery_score (score)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS study_sessions (
        session_id VARCHAR(64) NOT NULL PRIMARY KEY,
        user_id    VARCHAR(64) NOT NULL,
        topic      VARCHAR(255),
        started_at DATETIME(6) NOT NULL,
        ended_at   DATETIME(6)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS study_users (
        user_id      VARCHAR(64)  NOT NULL PRIMARY KEY,
        display_name VARCHAR(128) NOT NULL,
        created_at   DATETIME(6)  NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS study_traces (
        trace_id     VARCHAR(64) NOT NULL PRIMARY KEY,
        session_id   VARCHAR(64) NOT NULL,
        ts           DATETIME(6) NOT NULL,
        layer        VARCHAR(32) NOT NULL,
        operation    VARCHAR(64) NOT NULL,
        input_text   TEXT,
        result_count INT         NOT NULL DEFAULT 0,
        summary      TEXT,
        payload_json LONGTEXT,
        KEY idx_trace_session_time (session_id, ts)
    )
    """,
)
