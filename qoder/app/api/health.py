"""Health endpoint.

Reports process health plus a real seekdb probe (document and chunk counts).
PowerContext is reported as ``not_checked`` until the S3 client is wired in,
rather than claiming an integration that has not been exercised.
"""

from datetime import datetime, timezone

from fastapi import APIRouter

from ..config import settings
from ..seekdb import db

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    seekdb_state: dict
    try:
        seekdb_state = {"status": "ok", **db.health()}
    except Exception as exc:
        seekdb_state = {"status": "error", "detail": f"{type(exc).__name__}: {exc}"}

    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.version,
        "stage": settings.stage,
        "time": datetime.now(timezone.utc).isoformat(),
        "runtime": {
            "host": settings.host,
            "port": settings.port,
            "user_id": settings.user_id,
            "seekdb_path": str(settings.seekdb_path),
        },
        "integrations": {
            "seekdb": seekdb_state,
            "powercontext": {"url": settings.powercontext_url, "probe": "not_checked_until_s3"},
            "embedding": {
                "mode": settings.embedding_mode,
                "model": settings.embedding_model,
                "dimension": settings.embedding_dim,
            },
            "llm": "optional_not_configured",
        },
    }
