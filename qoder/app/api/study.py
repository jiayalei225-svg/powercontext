"""HTTP surface for retrieval, ingest and the trace panel."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from ..config import settings
from ..ingest import knowledge, pipeline
from ..retrieval import hybrid
from ..seekdb import db, repo

router = APIRouter(prefix="/api", tags=["study"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    mode: str = "hybrid"
    subject: str | None = None
    doc_id: str | None = None
    section: str | None = None
    top_k: int = 10
    session_id: str = "web"


class SeedRequest(BaseModel):
    force: bool = False
    session_id: str = "web"


def _guard(callable_, *args, **kwargs):
    try:
        return callable_(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # surface the real reason instead of a blank 500
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@router.post("/search")
def api_search(request: SearchRequest) -> dict:
    return _guard(
        hybrid.search,
        request.query,
        mode=request.mode,
        subject=request.subject,
        doc_id=request.doc_id,
        section=request.section,
        top_k=request.top_k,
        session_id=request.session_id,
    )


@router.get("/documents")
def api_documents() -> dict:
    return _guard(
        lambda: {
            "documents": repo.list_documents(),
            "stats": pipeline.stats(),
        }
    )


@router.post("/ingest/seed")
def api_ingest_seed(request: SeedRequest) -> dict:
    return _guard(
        lambda: {
            "results": pipeline.import_seed(
                session_id=request.session_id, force=request.force
            ),
            "stats": pipeline.stats(),
        }
    )


@router.post("/ingest/upload")
async def api_ingest_upload(
    file: UploadFile = File(...),
    subject: str = Form("未分类"),
    session_id: str = Form("web"),
) -> dict:
    name = Path(file.filename or "upload.md").name
    suffix = Path(name).suffix.lower()
    if suffix not in {".md", ".markdown", ".txt", ".text", ".pdf"}:
        raise HTTPException(status_code=400, detail="仅支持 md / txt / pdf")

    upload_dir = settings.upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_prefix = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(name).stem)[:40] or "doc"
    target = upload_dir / f"{safe_prefix}-{uuid4().hex[:8]}{suffix}"
    with target.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)
    await file.close()

    doc_id = f"{safe_prefix}-{uuid4().hex[:6]}".lower()
    result = _guard(
        pipeline.import_file,
        target,
        subject=subject,
        doc_id=doc_id,
        title=Path(name).stem,
        session_id=session_id,
    )
    return {"result": result, "stats": _guard(pipeline.stats)}


@router.get("/traces")
def api_traces(
    session_id: str | None = Query(default=None),
    limit: int = Query(default=60, ge=1, le=200),
) -> dict:
    return _guard(lambda: {"traces": repo.list_traces(session_id, limit)})


@router.get("/stats")
def api_stats() -> dict:
    return _guard(pipeline.stats)


@router.delete("/documents/{doc_id}")
def api_delete_document(doc_id: str) -> dict:
    def run() -> dict:
        db.collection().delete(where={"doc_id": doc_id})
        repo.delete_document_row(doc_id)
        knowledge.rebuild(session_id="delete")
        return {"deleted": doc_id}

    return _guard(run)
