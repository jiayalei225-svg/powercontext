"""Ingest pipeline: file -> chunks -> seekdb (collection + documents table).

The pipeline is idempotent: a file whose ``content_hash`` is unchanged is
skipped, and a changed file replaces its old chunks before writing new ones.
Every run writes one trace row so the UI can prove the import really happened.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from ..config import settings
from ..seekdb import db, repo
from ..trace.models import LAYER_SEEKDB, TraceEvent
from . import chunker, loaders

SUPPORTED = {".md", ".markdown", ".txt", ".text", ".pdf"}


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(settings.data_dir.parent).as_posix()
    except ValueError:
        return path.name


def _build_chunks(doc_id: str, loaded: loaders.LoadedDocument) -> list[chunker.Chunk]:
    if loaded.file_type in {"md", "markdown"}:
        return chunker.chunk_markdown(doc_id, loaded.text)
    chunks: list[chunker.Chunk] = []
    for page, text in loaded.pages:
        if not text.strip():
            continue
        section = f"第 {page} 页" if loaded.file_type == "pdf" else "正文"
        chunks.extend(
            chunker.chunk_plain(
                doc_id,
                text,
                page=page,
                section=section,
                start_index=len(chunks),
            )
        )
    return chunks


def _metadata(doc: dict, chunk: chunker.Chunk) -> dict:
    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": doc["doc_id"],
        "doc_title": doc["title"],
        "subject": doc["subject"],
        "section": chunk.section,
        "page": int(chunk.page),
        "chunk_index": int(chunk.index),
        "source_path": doc["source_path"],
        "imported_at": doc["imported_at"],
    }


def import_file(
    path: Path,
    *,
    subject: str | None = None,
    doc_id: str | None = None,
    title: str | None = None,
    session_id: str = "ingest",
    force: bool = False,
) -> dict:
    if path.suffix.lower() not in SUPPORTED:
        raise ValueError(f"暂不支持 {path.suffix}，请上传 md / txt / pdf")

    loaded = loaders.load(path)
    raw = path.read_bytes()
    content_hash = hashlib.sha256(raw).hexdigest()
    meta = loaded.meta
    doc_id = str(doc_id or meta.get("doc_id") or "").strip()
    if not doc_id:
        raise ValueError("文档缺少 doc_id")
    if title:
        meta["title"] = title
    subject_value = (subject or meta.get("subject") or "未分类").strip()

    existing = repo.get_document(doc_id)
    if existing and not force and existing.get("content_hash") == content_hash:
        event = TraceEvent(
            session_id=session_id,
            layer=LAYER_SEEKDB,
            operation="ingest_document",
            input_text=_relative(path),
            result_count=0,
            summary=f"跳过 {existing['title']}：内容哈希未变化",
            payload={"doc_id": doc_id, "skipped": True, "content_hash": content_hash},
        )
        repo.save_trace(event)
        return {
            "doc_id": doc_id,
            "title": existing["title"],
            "subject": existing["subject"],
            "chunks": int(existing["chunk_count"]),
            "skipped": True,
            "trace_id": event.trace_id,
        }

    chunks = _build_chunks(doc_id, loaded)
    if not chunks:
        raise ValueError(f"{path.name} 没有可索引的文本")

    imported_at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    doc = {
        "doc_id": doc_id,
        "title": str(meta.get("title") or path.stem),
        "subject": subject_value,
        "source_path": _relative(path),
        "file_type": loaded.file_type,
        "page_count": max((page for page, _ in loaded.pages), default=0),
        "chunk_count": len(chunks),
        "content_hash": content_hash,
        "imported_at": imported_at,
    }

    collection = db.collection()
    collection.delete(where={"doc_id": doc_id})
    for start in range(0, len(chunks), 64):
        batch = chunks[start : start + 64]
        collection.upsert(
            ids=[chunk.chunk_id for chunk in batch],
            documents=[chunk.text for chunk in batch],
            metadatas=[_metadata(doc, chunk) for chunk in batch],
        )
    collection.refresh_index()
    repo.upsert_document(doc)

    event = TraceEvent(
        session_id=session_id,
        layer=LAYER_SEEKDB,
        operation="ingest_document",
        input_text=_relative(path),
        result_count=len(chunks),
        summary=f"写入 {doc['title']}：{len(chunks)} 个 chunk（{doc['subject']}）",
        payload={
            "doc_id": doc_id,
            "title": doc["title"],
            "subject": doc["subject"],
            "file_type": doc["file_type"],
            "content_hash": content_hash,
            "chunks": [
                {"chunk_id": c.chunk_id, "section": c.section, "page": c.page}
                for c in chunks[:8]
            ],
        },
    )
    repo.save_trace(event)

    return {
        "doc_id": doc_id,
        "title": doc["title"],
        "subject": doc["subject"],
        "chunks": len(chunks),
        "skipped": False,
        "trace_id": event.trace_id,
    }


def import_seed(*, session_id: str = "ingest", force: bool = False) -> list[dict]:
    seed_dir = settings.seed_dir
    results = []
    for path in sorted(seed_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in SUPPORTED:
            results.append(import_file(path, session_id=session_id, force=force))
    return results


def stats() -> dict:
    docs = repo.list_documents()
    return {
        "documents": len(docs),
        "chunks": db.collection().count(),
        "subjects": sorted({doc["subject"] for doc in docs}),
        "embedding": {
            "mode": settings.embedding_mode,
            "model": settings.embedding_model,
            "dimension": settings.embedding_dim,
        },
    }
