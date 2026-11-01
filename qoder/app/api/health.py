"""Health endpoint.

Reports process health plus real probes for seekdb and PowerContext. The
PowerContext probe is its readiness endpoint, so the response cannot claim a
memory layer that is not actually reachable.
"""

from datetime import datetime, timezone

from fastapi import APIRouter

from ..config import settings
from ..memory import service as memory_service
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
            "powercontext": memory_service.probe(),
            "embedding": {
                "mode": settings.embedding_mode,
                "model": settings.embedding_model,
                "dimension": settings.embedding_dim,
            },
            "llm": settings.llm_model or "evidence_only",
        },
    }
