"""Health endpoint.

It reports process health only. Real seekdb and PowerContext probes are added
in S2 and S3; until then the response explicitly says ``not_checked`` instead
of pretending the integrations are verified.
"""

from datetime import datetime, timezone

from fastapi import APIRouter

from ..config import settings

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
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
            "seekdb": "configured_not_probed",
            "powercontext": {"url": settings.powercontext_url, "probe": "not_checked_until_s3"},
            "embedding": {"mode": settings.embedding_mode, "model": settings.embedding_model},
            "llm": "optional_not_configured",
        },
    }
