"""Runtime configuration.

The app must start with nothing but ``pip install -r requirements.txt``, so the
.env loader is dependency-free. Every path is resolved relative to ``qoder/``
so the repository stays self-contained and nothing is written outside it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


def _text(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


def _number(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _integer(name: str, default: int) -> int:
    return int(_number(name, default))


def _path(name: str, default: str) -> Path:
    resolved = Path(_text(name, default))
    return resolved if resolved.is_absolute() else ROOT / resolved


@dataclass(frozen=True)
class Settings:
    app_name: str = "StudyCoach"
    version: str = "0.5.0"
    stage: str = _text("APP_STAGE", "S5")

    host: str = _text("APP_HOST", "127.0.0.1")
    port: int = _integer("APP_PORT", 8090)
    user_id: str = _text("USER_ID", "local")

    data_dir: Path = _path("DATA_DIR", "./data")
    seekdb_path: Path = _path("SEEKDB_PATH", "./data/seekdb")
    model_dir: Path = _path("MODEL_DIR", "./data/models")

    powercontext_url: str = _text("POWERCONTEXT_URL", "http://127.0.0.1:8010").rstrip("/")
    powercontext_scope_id: str = _text("POWERCONTEXT_SCOPE_ID", "")

    embedding_mode: str = _text("EMBEDDING_MODE", "local").lower()
    embedding_model: str = _text("EMBEDDING_MODEL", "bge-small-zh-v1.5")
    embedding_hf_id: str = _text("EMBEDDING_HF_ID", "Xenova/bge-small-zh-v1.5")
    embedding_dim: int = _integer("EMBEDDING_DIM", 512)

    hybrid_vector_weight: float = _number("HYBRID_VECTOR_WEIGHT", 0.6)
    hybrid_fts_weight: float = _number("HYBRID_FTS_WEIGHT", 0.4)
    hybrid_top_k: int = _integer("HYBRID_TOP_K", 10)

    mastery_alpha: float = _number("MASTERY_ALPHA", 0.25)
    mastery_beta: float = _number("MASTERY_BETA", 0.20)
    decay_days: int = _integer("DECAY_DAYS", 14)
    decay_factor: float = _number("DECAY_FACTOR", 0.85)

    llm_base_url: str = _text("LLM_BASE_URL", "").rstrip("/")
    llm_api_key: str = _text("LLM_API_KEY", "")
    llm_model: str = _text("LLM_MODEL", "")

    web_dir: Path = ROOT / "app" / "web"

    @property
    def seed_dir(self) -> Path:
        return self.data_dir / "seed"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    def prepare(self) -> None:
        for path in (self.data_dir, self.seekdb_path, self.model_dir, self.seed_dir, self.upload_dir):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
