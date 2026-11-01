"""Script entry point.

The one-click scripts delegate to this module instead of hard-coding a port,
so ``APP_HOST`` / ``APP_PORT`` in ``.env`` remain the single source of truth.
"""

import uvicorn

from .config import settings

if __name__ == "__main__":
    settings.prepare()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port)
