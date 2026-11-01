"""Embedded seekdb access: one data directory, two handles.

* ``pyseekdb.Client`` owns the ``study_chunks`` collection (vectors, full-text
  index, scalar metadata).
* ``pylibseekdb.open`` starts the embedded instance and exposes the MySQL
  protocol. ``pymysql`` then runs the relational tables with real parameter
  binding, which the low-level cursor (string-only ``execute``) cannot do.

Both handles point at ``SEEKDB_PATH``. seekdb is embedded, so there is no
server process to start and ``git clone`` + ``pip install`` is enough.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Iterator

import pymysql
import pylibseekdb
import pyseekdb
from pymysql.cursors import DictCursor

from ..config import settings
from .schema import COLLECTION_NAME, DDL_STATEMENTS

_lock = threading.RLock()
_state: dict[str, Any] = {}


def _instance() -> Any:
    with _lock:
        if "instance" not in _state:
            settings.prepare()
            _state["instance"] = pylibseekdb.open(str(settings.seekdb_path))
        return _state["instance"]


def _connection() -> pymysql.Connection:
    with _lock:
        conn = _state.get("connection")
        if conn is None or not conn.open:
            options = _instance().connection_options()
            conn = pymysql.connect(
                **options,
                database="test",
                autocommit=True,
                charset="utf8mb4",
                cursorclass=DictCursor,
            )
            _state["connection"] = conn
        return conn


@contextmanager
def sql() -> Iterator[DictCursor]:
    """Serialized SQL access with parameter binding."""
    with _lock:
        conn = _connection()
        cursor = conn.cursor()
        try:
            yield cursor
        finally:
            cursor.close()


def execute(statement: str, params: tuple | list = ()) -> int:
    with sql() as cursor:
        cursor.execute(statement, params)
        return cursor.rowcount


def execute_many(statement: str, rows: list[tuple] | list[list]) -> int:
    if not rows:
        return 0
    with sql() as cursor:
        cursor.executemany(statement, rows)
        return cursor.rowcount


def query_all(statement: str, params: tuple | list = ()) -> list[dict]:
    with sql() as cursor:
        cursor.execute(statement, params)
        return list(cursor.fetchall())


def query_one(statement: str, params: tuple | list = ()) -> dict | None:
    rows = query_all(statement, params)
    return rows[0] if rows else None


def init_schema() -> None:
    """Create every table once. Safe to call on each process start."""
    with sql() as cursor:
        for statement in DDL_STATEMENTS:
            cursor.execute(statement)
    ensure_user(settings.user_id)


def ensure_user(user_id: str) -> None:
    with sql() as cursor:
        cursor.execute(
            "INSERT IGNORE INTO study_users (user_id, display_name, created_at) VALUES (%s, %s, UTC_TIMESTAMP(6))",
            (user_id, user_id),
        )


def _embedding_function() -> Any:
    from pyseekdb.utils.embedding_functions import OnnxEmbeddingFunction

    return OnnxEmbeddingFunction(
        model_name=settings.embedding_model,
        hf_model_id=settings.embedding_hf_id,
        dimension=settings.embedding_dim,
    )


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed texts with the same local model seekdb uses.

    PowerContext cannot run its own ONNX runtime, so StudyCoach exposes this
    model through ``POST /v1/embeddings``. Sharing one function instance keeps
    the memory index and the document index in the same vector space.
    """
    if not texts:
        return []
    with _lock:
        if "embedding" not in _state:
            settings.prepare()
            _state["embedding"] = _embedding_function()
        function = _state["embedding"]
        return function(texts)


def collection() -> Any:
    """The single hybrid collection, opened lazily."""
    with _lock:
        if "collection" not in _state:
            settings.prepare()
            client = pyseekdb.Client(path=str(settings.seekdb_path))
            _state["client"] = client
            _state["collection"] = client.get_or_create_collection(
                name=COLLECTION_NAME,
                embedding_function=_embedding_function(),
            )
        return _state["collection"]


def reset() -> None:
    """Drop cached handles (tests and ``--reset`` re-import use this)."""
    with _lock:
        conn = _state.pop("connection", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        client = _state.pop("client", None)
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        instance = _state.pop("instance", None)
        if instance is not None:
            try:
                instance.close()
            except Exception:
                pass


def health() -> dict:
    docs = query_one("SELECT COUNT(*) AS n FROM study_documents") or {"n": 0}
    points = query_one("SELECT COUNT(*) AS n FROM study_knowledge_points") or {"n": 0}
    chunks = collection().count()
    return {
        "embedded_path": str(settings.seekdb_path),
        "documents": int(docs["n"]),
        "chunks": int(chunks),
        "knowledge_points": int(points["n"]),
        "collection": COLLECTION_NAME,
    }
