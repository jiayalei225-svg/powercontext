"""FastAPI entry point.

Feature routers are mounted stage by stage, but the app always boots: schema
creation happens in the lifespan hook, so a fresh clone creates its embedded
seekdb directory on first start.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.coach import router as coach_router
from .api.embeddings import router as embeddings_router
from .api.health import router as health_router
from .api.study import router as study_router
from .config import settings
from .seekdb import db


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.prepare()
    db.init_schema()
    yield


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
app.include_router(health_router)
app.include_router(embeddings_router)
app.include_router(study_router)
app.include_router(coach_router)
app.mount("/static", StaticFiles(directory=str(settings.web_dir)), name="static")


@app.get("/", include_in_schema=False)
def homepage() -> FileResponse:
    return FileResponse(settings.web_dir / "index.html")
