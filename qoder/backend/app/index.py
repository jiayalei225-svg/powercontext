"""seekdb storage: paper chunks in one hybrid collection."""

from __future__ import annotations

import threading
from typing import Any

import pyseekdb

from .embedding import active_label, resolve
from .pdf import Chunk, PaperMeta
from .settings import settings

NAMESPACE = "paper_chunks_v2"

_lock = threading.Lock()
_handle: dict[str, Any] = {}
_corpus: list[str] | None = None


def _drop_corpus() -> None:
    global _corpus
    _corpus = None


def _collection():
    with _lock:
        if "ref" in _handle:
            return _handle["ref"]
        embedder, suffix, _ = resolve()
        client = pyseekdb.Client(path=str(settings.seekdb_dir))
        ref = client.get_or_create_collection(
            name=f"{NAMESPACE}_{suffix}", embedding_function=embedder
        )
        _handle["ref"] = ref
        _handle["name"] = f"{NAMESPACE}_{suffix}"
        return ref


def collection_name() -> str:
    _collection()
    return _handle["name"]


def reset() -> None:
    with _lock:
        _handle.clear()
        _drop_corpus()


def _row(meta: PaperMeta, chunk: Chunk, paper_id: str) -> dict:
    return {
        "paper_id": paper_id,
        "title": meta.title,
        "year": int(meta.year or 0),
        "venue": meta.venue or "未标注",
        "field": meta.field or "未分类",
        "source": meta.source,
        "has_code": 1 if meta.has_code else 0,
        "code_url": meta.code_url or "",
        "page": int(chunk.page),
        "seq": int(chunk.index),
    }


def exists(paper_id: str) -> bool:
    found = _collection().get(where={"paper_id": paper_id}, include=["metadatas"], limit=1)
    return bool(found.get("ids"))


def add(paper_id: str, meta: PaperMeta, chunks: list[Chunk]) -> int:
    if not chunks:
        return 0
    ref = _collection()
    ref.delete(where={"paper_id": paper_id})
    batch = 48
    for start in range(0, len(chunks), batch):
        window = chunks[start : start + batch]
        ref.upsert(
            ids=[f"{paper_id}:{chunk.index}" for chunk in window],
            documents=[chunk.text for chunk in window],
            metadatas=[_row(meta, chunk, paper_id) for chunk in window],
        )
    ref.refresh_index()
    _drop_corpus()
    return len(chunks)


def remove(paper_id: str) -> bool:
    if not exists(paper_id):
        return False
    _collection().delete(where={"paper_id": paper_id})
    _collection().refresh_index()
    _drop_corpus()
    return True


def _group(metadatas: list[dict]) -> dict[str, dict]:
    grouped: dict[str, dict] = {}
    counts: dict[str, int] = {}
    for row in metadatas:
        pid = row["paper_id"]
        counts[pid] = counts.get(pid, 0) + 1
        entry = grouped.setdefault(
            pid,
            {
                "paper_id": pid,
                "title": row.get("title"),
                "year": row.get("year") or None,
                "venue": row.get("venue"),
                "field": row.get("field"),
                "source": row.get("source"),
                "has_code": bool(row.get("has_code")),
                "code_url": row.get("code_url") or None,
                "pages": 0,
            },
        )
        entry["pages"] = max(entry["pages"], int(row.get("page") or 0))
    for pid, entry in grouped.items():
        entry["chunks"] = counts[pid]
    return grouped


def papers() -> list[dict]:
    result = _collection().get(include=["metadatas"], limit=20000)
    grouped = _group(result.get("metadatas") or [])
    return sorted(grouped.values(), key=lambda item: (item.get("year") or 0, item["title"]), reverse=True)


def paper(paper_id: str) -> dict | None:
    result = _collection().get(
        where={"paper_id": paper_id}, include=["documents", "metadatas"], limit=20000
    )
    ids = result.get("ids") or []
    if not ids:
        return None
    metadatas = result.get("metadatas") or []
    documents = result.get("documents") or []
    grouped = _group(metadatas)
    entry = grouped.get(paper_id)
    if entry is None:
        return None
    rows = []
    for index, row in enumerate(metadatas):
        rows.append(
            {
                "chunk_id": ids[index],
                "text": documents[index] if index < len(documents) else "",
                "page": row.get("page"),
                "seq": row.get("seq"),
            }
        )
    rows.sort(key=lambda item: (item.get("page") or 0, item.get("seq") or 0))
    entry["chunk_details"] = rows
    return entry


def stats() -> dict:
    summary = papers()
    return {
        "collection": collection_name(),
        "papers": len(summary),
        "chunks": sum(item["chunks"] for item in summary),
        "embedding": active_label(),
    }


def _corpus_texts() -> list[str]:
    global _corpus
    if _corpus is None:
        result = _collection().get(include=["documents"], limit=20000)
        _corpus = [text for text in (result.get("documents") or []) if text]
    return _corpus


def literal_count(term: str) -> int:
    if not term:
        return 0
    return sum(1 for text in _corpus_texts() if term in text)


def warm() -> None:
    """Pay the ONNX load and corpus scan before the first user query."""
    try:
        nearest("预热", None, 1)
        _corpus_texts()
    except Exception:
        pass


def build_where(filters: dict) -> dict | None:
    where: dict = {}
    if filters.get("year_from"):
        where["year"] = {"$gte": int(filters["year_from"])}
    if filters.get("year_to"):
        bound = where.get("year", {})
        bound["$lte"] = int(filters["year_to"])
        where["year"] = bound
    if filters.get("venues"):
        where["venue"] = {"$in": list(filters["venues"])}
    if filters.get("field"):
        where["field"] = filters["field"]
    if filters.get("paper_id"):
        where["paper_id"] = filters["paper_id"]
    if filters.get("has_code"):
        where["has_code"] = 1
    return where or None


def _normalize(result: dict) -> list[dict]:
    ids = (result.get("ids") or [[]])[0]
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    hits = []
    for position, chunk_id in enumerate(ids):
        row = metadatas[position] if position < len(metadatas) else {}
        hits.append(
            {
                "chunk_id": chunk_id,
                "text": documents[position] if position < len(documents) else "",
                "metadata": row,
                "score": distances[position] if position < len(distances) else None,
            }
        )
    return hits


def hybrid(query: str, literal: str | None, where: dict | None, limit: int) -> list[dict]:
    ref = _collection()
    fulltext: dict = {"n_results": limit * 3}
    if literal:
        fulltext["where_document"] = {"$contains": literal}
    if where:
        fulltext["where"] = where
    knn: dict = {"query_texts": [query], "n_results": limit * 3}
    if where:
        knn["where"] = where
    result = ref.hybrid_search(
        query=fulltext,
        knn=knn,
        rank={"rrf": {"rank_window_size": 60, "rank_constant": 60}},
        n_results=limit,
        include=["documents", "metadatas", "distances"],
    )
    return _normalize(result)


def nearest(query: str, where: dict | None, limit: int) -> list[dict]:
    result = _collection().query(
        query_texts=[query],
        n_results=limit,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    return _normalize(result)
