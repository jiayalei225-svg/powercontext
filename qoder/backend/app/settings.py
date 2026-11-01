"""Runtime settings for PaperDesk 2.0.

Everything is environment-driven so the same tree runs on a reviewer's
machine without editing code. The one non-obvious rule is the data directory:
seekdb's native layer cannot open a database below a path containing
non-ASCII characters, so we transparently fall back to %LOCALAPPDATA%.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VERSION = "2.0.0"


def _read_env(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_read_env(PROJECT_ROOT / ".env")


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _ascii_only(path: Path) -> bool:
    try:
        str(path).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _pick_data_dir() -> Path:
    configured = os.environ.get("PAPERDESK_DATA_DIR", "").strip()
    candidate = Path(configured).expanduser() if configured else PROJECT_ROOT / "data"
    try:
        candidate = candidate.resolve()
    except OSError:
        pass
    if _ascii_only(candidate):
        return candidate
    fallback = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "PaperDesk" / "data-v2"
    print(
        f"[PaperDesk] {candidate} contains non-ASCII characters and seekdb cannot "
        f"open it; using {fallback}. Set PAPERDESK_DATA_DIR to override.",
        flush=True,
    )
    return fallback


@dataclass
class Settings:
    data_dir: Path = field(default_factory=_pick_data_dir)
    embedding_mode: str = field(default_factory=lambda: os.environ.get("EMBEDDING_MODE", "local").strip().lower())
    embedding_base: str = field(default_factory=lambda: os.environ.get("EMBEDDING_API_BASE", "").strip())
    embedding_key: str = field(default_factory=lambda: os.environ.get("EMBEDDING_API_KEY", "").strip())
    embedding_model: str = field(default_factory=lambda: os.environ.get("EMBEDDING_MODEL", "").strip())
    embedding_dim: int = field(default_factory=lambda: int(os.environ.get("EMBEDDING_DIM", "0") or 0))
    powercontext_url: str = field(
        default_factory=lambda: os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:18000").rstrip("/")
    )
    powercontext_timeout: float = field(
        default_factory=lambda: float(os.environ.get("POWERCONTEXT_TIMEOUT", "6"))
    )
    memory_enabled: bool = field(default_factory=lambda: _flag("PAPERDESK_MEMORY_ENABLED", True))
    port: int = field(default_factory=lambda: int(os.environ.get("PAPERDESK_PORT", "8080")))
    version: str = VERSION

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
