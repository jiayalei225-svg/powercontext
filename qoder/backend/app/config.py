"""Runtime configuration, loaded from environment with sane defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("PAPERDESK_DATA_DIR", ROOT / "data")))
    embedding_mode: str = field(default_factory=lambda: os.environ.get("EMBEDDING_MODE", "local").strip().lower())
    embedding_api_base: str = field(default_factory=lambda: os.environ.get("EMBEDDING_API_BASE", "").strip())
    embedding_api_key: str = field(default_factory=lambda: os.environ.get("EMBEDDING_API_KEY", "").strip())
    embedding_model: str = field(default_factory=lambda: os.environ.get("EMBEDDING_MODEL", "").strip())
    embedding_dim: int = field(default_factory=lambda: int(os.environ.get("EMBEDDING_DIM", "0") or 0))
    powercontext_url: str = field(default_factory=lambda: os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:8000").rstrip("/"))
    powercontext_timeout: float = field(default_factory=lambda: float(os.environ.get("POWERCONTEXT_TIMEOUT", "5")))
    memory_enabled: bool = field(default_factory=lambda: _bool("PAPERDESK_MEMORY_ENABLED", True))

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def seekdb_dir(self) -> Path:
        return self.data_dir / "seekdb"

    def prepare(self) -> None:
        for path in (self.data_dir, self.upload_dir, self.seekdb_dir):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.prepare()
