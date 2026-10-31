"""HTTP API for the paper desk."""

from __future__ import annotations

import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ingest, memory, search, store
from .config import ROOT, settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Loading the embedding model and the jieba dictionary takes seconds; do it
    # at boot so the first search is not the one paying for it.
    store.stats()
    search.extract_keyword("预热")
    yield


app = FastAPI(title="PaperDesk", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_SUFFIX = {".pdf", ".md", ".txt"}


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    year_from: int | None = None
    year_to: int | None = None
    venues: list[str] = Field(default_factory=list)
    field: str | None = None
    paper_id: str | None = None
    has_code: bool | None = None
    limit: int = 12


class Preferences(BaseModel):
    default_year_from: int | None = None
    default_venues: list[str] = Field(default_factory=list)
    default_field: str | None = None
    require_code: bool = False
    topics: list[str] = Field(default_factory=list)
    reading_style: str | None = None


@app.get("/api/health")
def health():
    return {
        "seekdb": store.stats(),
        "memory": memory.available(),
        "memory_url": settings.powercontext_url,
    }


@app.get("/api/papers")
def papers():
    return {"papers": store.list_papers()}


@app.post("/api/papers/upload")
async def upload(
    file: UploadFile = File(...),
    venue: str = Form(""),
    field: str = Form(""),
    year: int | None = Form(None),
    has_code: bool = Form(False),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIX:
        raise HTTPException(400, f"只支持 {', '.join(sorted(ALLOWED_SUFFIX))} 格式")

    target = settings.upload_dir / (file.filename or "upload")
    if target.exists():
        target = settings.upload_dir / f"{target.stem}_{int(target.stat().st_mtime)}{suffix}"
    with target.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)

    paper_id = ingest.paper_id_for(target, file.filename or "")
    if store.paper_exists(paper_id):
        target.unlink(missing_ok=True)
        raise HTTPException(409, "这篇文献已经在库里了")

    doc = ingest.parse_document(target)
    if not doc.pages:
        target.unlink(missing_ok=True)
        raise HTTPException(422, "没能从文件里解析出文本，可能是扫描版 PDF")

    paper = {
        "paper_id": paper_id,
        "title": doc.title,
        "year": year or ingest.guess_year(doc.title, doc.pages[0].text),
        "venue": venue.strip() or doc.metadata.get("subject") or "未标注",
        "field": field.strip() or "未分类",
        "source": target.name,
        "has_code": has_code,
    }
    chunks = ingest.split_pages(doc.pages, paper_id)
    written = store.add_paper(paper, chunks)
    return {**paper, "chunks": written, "pages": len(doc.pages)}


@app.delete("/api/papers/{paper_id}")
def delete_paper(paper_id: str):
    store.delete_paper(paper_id)
    return {"deleted": paper_id}


@app.post("/api/search")
def do_search(request: SearchRequest):
    return search.run(request.query, request.model_dump(), limit=request.limit)


@app.get("/api/memory")
def read_memory():
    try:
        return memory.snapshot()
    except memory.MemoryError as exc:
        return {"connected": False, "error": str(exc), "preferences": {}, "searches": [], "entries": []}


@app.get("/api/preferences")
def get_preferences():
    try:
        return {"preferences": memory.load_preferences(), "memory_connected": True}
    except memory.MemoryError:
        return {"preferences": {}, "memory_connected": False}


@app.put("/api/preferences")
def put_preferences(prefs: Preferences):
    try:
        saved = memory.save_preferences(prefs.model_dump())
    except memory.MemoryError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {**saved, "memory_connected": True}


_frontend = ROOT / "frontend" / "dist"
if _frontend.is_dir():
    app.mount("/assets", StaticFiles(directory=_frontend / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(_frontend / "index.html")
