"""seekdb access layer: one collection holds every paper chunk."""

from __future__ import annotations

import threading
from typing import Any

import pyseekdb

from .config import settings
from .embeddings import build_embedding_function, embedding_signature
from .ingest import Chunk

COLLECTION_PREFIX = "paper_chunks"

_lock = threading.Lock()
_state: dict[str, Any] = {}
_corpus_texts: list[str] | None = None


def _invalidate_corpus() -> None:
    global _corpus_texts
    _corpus_texts = None


def _corpus() -> list[str]:
    """All chunk texts, cached in memory.

    Rarity probing used to issue one ``$contains`` query per candidate word;
    on a small corpus that dominated search latency (3 x ~2 s).  A cached text
    list turns it into a microsecond-scale Python scan.  Uploads and deletes
    invalidate the cache.
    """
    global _corpus_texts
    if _corpus_texts is None:
        result = _collection().get(include=["documents"], limit=20000)
        _corpus_texts = [text for text in (result.get("documents") or []) if text]
    return _corpus_texts


def _collection():
    with _lock:
        if "collection" in _state:
            return _state["collection"]
        fn, suffix = build_embedding_function()
        client = pyseekdb.Client(path=str(settings.seekdb_dir))
        name = f"{COLLECTION_PREFIX}_{suffix}"
        collection = client.get_or_create_collection(name=name, embedding_function=fn)
        _state["collection"] = collection
        _state["name"] = name
        return collection


def collection_name() -> str:
    _collection()
    return _state["name"]


def reset_handle() -> None:
    """Drop the cached handle so settings changes take effect (tests use this)."""
    with _lock:
        _state.clear()
        _invalidate_corpus()


def _chunk_metadata(paper: dict, chunk: Chunk) -> dict:
    return {
        "paper_id": paper["paper_id"],
        "title": paper["title"],
        "year": int(paper.get("year") or 0),
        "venue": paper.get("venue") or "未标注",
        "field": paper.get("field") or "未分类",
        "source": paper.get("source") or "",
        "has_code": 1 if paper.get("has_code") else 0,
        "page": int(chunk.page),
        "chunk_index": int(chunk.index),
    }


def add_paper(paper: dict, chunks: list[Chunk]) -> int:
    if not chunks:
        return 0
    collection = _collection()
    batch = 64
    written = 0
    for start in range(0, len(chunks), batch):
        window = chunks[start : start + batch]
        collection.upsert(
            ids=[c.chunk_id for c in window],
            documents=[c.text for c in window],
            metadatas=[_chunk_metadata(paper, c) for c in window],
        )
        written += len(window)
    collection.refresh_index()
    _invalidate_corpus()
    return written


def delete_paper(paper_id: str) -> None:
    _collection().delete(where={"paper_id": paper_id})
    _invalidate_corpus()


def paper_exists(path_hash: str) -> bool:
    found = _collection().get(where={"paper_id": path_hash}, include=["metadatas"], limit=1)
    return bool(found.get("ids"))


def list_papers() -> list[dict]:
    collection = _collection()
    result = collection.get(include=["metadatas"], limit=20000)
    papers: dict[str, dict] = {}
    counts: dict[str, int] = {}
    for meta in result.get("metadatas") or []:
        pid = meta["paper_id"]
        counts[pid] = counts.get(pid, 0) + 1
        papers.setdefault(
            pid,
            {
                "paper_id": pid,
                "title": meta["title"],
                "year": meta["year"] or None,
                "venue": meta["venue"],
                "field": meta["field"],
                "source": meta["source"],
                "has_code": bool(meta["has_code"]),
                "pages": 0,
            },
        )
        papers[pid]["pages"] = max(papers[pid]["pages"], int(meta["page"]))
    for pid, paper in papers.items():
        paper["chunks"] = counts[pid]
    return sorted(papers.values(), key=lambda p: (p["year"] or 0, p["title"]), reverse=True)


def stats() -> dict:
    collection = _collection()
    papers = list_papers()
    return {
        "collection": collection_name(),
        "papers": len(papers),
        "chunks": sum(p["chunks"] for p in papers),
        "embedding": embedding_signature(),
        "mode": settings.embedding_mode,
    }


def count_matches(keyword: str) -> int:
    """How many chunks literally contain this term — a cheap corpus rarity probe."""
    if not keyword:
        return 0
    return sum(1 for text in _corpus() if keyword in text)


def hybrid_search(query: str, keyword: str | None, where: dict | None, limit: int) -> list[dict]:
    """Vector + full-text + scalar filter fused with RRF inside seekdb."""
    collection = _collection()
    fulltext: dict = {"n_results": limit * 3}
    if keyword:
        fulltext["where_document"] = {"$contains": keyword}
    if where:
        fulltext["where"] = where

    knn: dict = {"query_texts": [query], "n_results": limit * 3}
    if where:
        knn["where"] = where

    result = collection.hybrid_search(
        query=fulltext,
        knn=knn,
        rank={"rrf": {"rank_window_size": 60, "rank_constant": 60}},
        n_results=limit,
        include=["documents", "metadatas", "distances"],
    )

    hits: list[dict] = []
    ids = (result.get("ids") or [[]])[0]
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    for i, chunk_id in enumerate(ids):
        hits.append(
            {
                "chunk_id": chunk_id,
                "text": documents[i],
                "metadata": metadatas[i],
                "score": distances[i] if i < len(distances) else None,
            }
        )
    return hits


def vector_only(query: str, where: dict | None, limit: int) -> list[dict]:
    collection = _collection()
    result = collection.query(query_texts=[query], n_results=limit, where=where, include=["documents", "metadatas", "distances"])
    hits: list[dict] = []
    ids = (result.get("ids") or [[]])[0]
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    for i, chunk_id in enumerate(ids):
        hits.append(
            {
                "chunk_id": chunk_id,
                "text": documents[i],
                "metadata": metadatas[i],
                "score": distances[i] if i < len(distances) else None,
            }
        )
    return hits
