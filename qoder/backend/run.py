"""Run the API: python backend/run.py"""

from __future__ import annotations

import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent))

if __name__ == "__main__":
    from app.config import settings

    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.port, reload=False)
