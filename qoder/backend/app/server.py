"""FastAPI surface for PaperDesk."""

from __future__ import annotations

import re
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import index, memory, pdf, recall, serialize
from .settings import PROJECT_ROOT, settings

MAX_UPLOAD = 40 * 1024 * 1024
DIST = PROJECT_ROOT / "frontend" / "dist"

@asynccontextmanager
async def lifespan(_: FastAPI):
    threading.Thread(target=index.warm, daemon=True).start()
    yield


app = FastAPI(
    title="PaperDesk",
    version=settings.version,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)


class SearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=12, ge=1, le=50)
    year_from: int | None = Field(default=None, ge=1900, le=2100)
    year_to: int | None = Field(default=None, ge=1900, le=2100)
    venues: list[str] | None = None
    field: str | None = Field(default=None, max_length=60)
    has_code: bool | None = None
    paper_id: str | None = Field(default=None, max_length=64)
    use_memory: bool = True


class Preferences(BaseModel):
    year_from: int | None = Field(default=None, ge=1900, le=2100)
    venues: list[str] = Field(default_factory=list)
    only_with_code: bool = False
    field: str | None = Field(default=None, max_length=60)


def _prefs_payload(prefs: Preferences) -> dict:
    venues: list[str] = []
    for venue in prefs.venues:
        cleaned = venue.strip()
        if cleaned and cleaned not in venues:
            venues.append(cleaned[:60])
    field_name = (prefs.field or "").strip()
    payload: dict = {"year_from": prefs.year_from, "venues": venues[:10]}
    if prefs.only_with_code:
        payload["only_with_code"] = True
    if field_name:
        payload["field"] = field_name
    return {key: value for key, value in payload.items() if value}


@app.get("/api/health")
def health() -> dict:
    connected = memory.enabled()
    return {
        "status": "ok",
        "version": settings.version,
        "data_dir": str(settings.data_dir),
        "index": index.stats(),
        "memory": {
            "connected": connected,
            "url": settings.powercontext_url,
            "scope_id": memory.scope() if connected else None,
        },
    }


@app.get("/api/papers")
def list_papers() -> dict:
    papers = index.papers()
    return {"papers": papers, "total": len(papers)}


@app.post("/api/papers")
async def upload_paper(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="PDF 超过 40MB 上限")
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="只接受 PDF 文件")

    paper_id = pdf.digest(data)
    target = settings.upload_dir / f"{paper_id}.pdf"
    if not target.is_file():
        target.write_bytes(data)
    if index.exists(paper_id):
        return {"duplicate": True, "added": 0, "paper": index.paper(paper_id)}

    filename = Path(file.filename or "paper.pdf").name
    try:
        pages = pdf.read_pages(target)
        if sum(len(page.strip()) for page in pages) < 200:
            raise HTTPException(status_code=422, detail="未能抽取到文本，扫描版 PDF 暂不支持")
        meta = pdf.read_meta(pages, filename)
        chunks = pdf.split_pages(pages)
        added = index.add(paper_id, meta, chunks)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"解析失败：{exc}") from exc

    return {"duplicate": False, "added": added, "paper": index.paper(paper_id)}


@app.get("/api/papers/{paper_id}")
def get_paper(paper_id: str) -> dict:
    detail = index.paper(paper_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    detail["has_pdf"] = (settings.upload_dir / f"{paper_id}.pdf").is_file()
    return detail


@app.get("/api/papers/{paper_id}/file")
def get_paper_file(paper_id: str) -> FileResponse:
    path = settings.upload_dir / f"{paper_id}.pdf"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="原始 PDF 不可用")
    detail = index.paper(paper_id) or {}
    name = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", detail.get("title") or paper_id) + ".pdf"
    return FileResponse(path, media_type="application/pdf", filename=name)


@app.delete("/api/papers/{paper_id}")
def delete_paper(paper_id: str) -> dict:
    removed = index.remove(paper_id)
    if not removed:
        raise HTTPException(status_code=404, detail="论文不存在")
    (settings.upload_dir / f"{paper_id}.pdf").unlink(missing_ok=True)
    return {"removed": True, "paper_id": paper_id}


@app.post("/api/search")
def search(body: SearchBody) -> dict:
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="检索词不能为空")
    request = body.model_dump(exclude={"query", "limit"})
    return recall.execute(query, request, body.limit)


@app.post("/api/search/export")
def export(body: SearchBody) -> Response:
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="检索词不能为空")
    request = body.model_dump(exclude={"query", "limit"})
    payload = recall.execute(query, request, body.limit)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    markdown = serialize.markdown(payload)
    response = Response(markdown, media_type="text/markdown; charset=utf-8")
    response.headers["Content-Disposition"] = f'attachment; filename="paperdesk-{stamp}.md"'
    return response


@app.post("/api/search/export.csv")
def export_csv(body: SearchBody) -> Response:
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="检索词不能为空")
    request = body.model_dump(exclude={"query", "limit"})
    payload = recall.execute(query, request, body.limit)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    response = Response(serialize.csv_text(payload), media_type="text/csv; charset=utf-8")
    response.headers["Content-Disposition"] = f'attachment; filename="paperdesk-{stamp}.csv"'
    return response


@app.get("/api/history")
def history(limit: int = 12) -> dict:
    limit = max(1, min(limit, 50))
    connected = memory.enabled()
    if not connected:
        return {"connected": False, "searches": []}
    try:
        return {"connected": True, "searches": memory.trail(limit)}
    except memory.MemoryError as exc:
        return {"connected": False, "searches": [], "error": str(exc)}


@app.get("/api/preferences")
def get_preferences(fresh: bool = False) -> dict:
    connected = memory.enabled()
    if not connected:
        return {"connected": False, "preferences": {}}
    try:
        return {"connected": True, "preferences": memory.load_prefs(fresh=fresh)}
    except memory.MemoryError as exc:
        return {"connected": False, "preferences": {}, "error": str(exc)}


@app.put("/api/preferences")
def put_preferences(body: Preferences) -> dict:
    if not memory.enabled():
        raise HTTPException(status_code=503, detail="PowerContext 未连接，偏好无法持久化")
    prefs = _prefs_payload(body)
    try:
        saved = memory.save_prefs(prefs)
    except memory.MemoryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"connected": True, **saved}


@app.get("/api/memory")
def get_memory() -> dict:
    try:
        return memory.snapshot()
    except memory.MemoryError as exc:
        return {"connected": False, "preferences": {}, "searches": [], "memories": [], "error": str(exc)}


if DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="ui")
else:

    @app.get("/")
    def placeholder() -> dict:
        return {"app": "PaperDesk", "version": settings.version, "ui": "frontend/dist 尚未构建"}
