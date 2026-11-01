"""Entry point: python backend/run.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn

from app.settings import settings

if __name__ == "__main__":
    print(f"[PaperDesk] http://127.0.0.1:{settings.port}  (data: {settings.data_dir})", flush=True)
    uvicorn.run("app.server:app", host="127.0.0.1", port=settings.port, log_level="info")
