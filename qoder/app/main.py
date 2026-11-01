"""FastAPI entry point.

Only system routes are mounted here. Feature routers are added under
``app/api/`` stage by stage so every stage stays independently runnable.
"""

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.health import router as health_router
from .config import settings

app = FastAPI(title=settings.app_name, version=settings.version)
app.include_router(health_router)
app.mount("/static", StaticFiles(directory=str(settings.web_dir)), name="static")


@app.get("/", include_in_schema=False)
def homepage() -> FileResponse:
    return FileResponse(settings.web_dir / "index.html")
