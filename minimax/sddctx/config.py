"""配置。

所有路径与外部服务地址都可以用环境变量覆盖，默认值面向"仓库内一条命令跑通"。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent.parent  # minimax/


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _load_dotenv() -> None:
    """极简 .env 加载：只在变量未设置时填充，不覆盖已有环境变量。"""
    env_file = MODULE_ROOT / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class Settings:
    """运行期配置。"""

    module_root: Path = MODULE_ROOT
    project_root: Path = field(default_factory=lambda: MODULE_ROOT / "sample_project")
    specs_dir: Path = field(default_factory=lambda: MODULE_ROOT / "samples" / "specs" / "v1")
    data_dir: Path = field(default_factory=lambda: MODULE_ROOT / ".data")
    budget_bytes: int = 24_000

    powercontext_url: str = "http://127.0.0.1:8099"
    minimax_api_key: str | None = None
    minimax_base_url: str = "https://api.minimax.chat/v1"
    minimax_model: str = "MiniMax-M1"
    minimax_max_tokens: int = 24_000
    minimax_timeout: float = 600.0

    @classmethod
    def load(cls, **overrides) -> "Settings":
        _load_dotenv()
        settings = cls(
            powercontext_url=_env("SDDCTX_POWERCONTEXT_URL", "http://127.0.0.1:8099"),
            minimax_api_key=_env("MINIMAX_API_KEY"),
            minimax_base_url=_env("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
            minimax_model=_env("MINIMAX_MODEL", "MiniMax-M1"),
            minimax_max_tokens=int(_env("MINIMAX_MAX_TOKENS", "24000")),
            budget_bytes=int(_env("SDDCTX_BUDGET_BYTES", "24000")),
            data_dir=Path(_env("SDDCTX_DATA_DIR", str(MODULE_ROOT / ".data"))),
            project_root=Path(_env("SDDCTX_PROJECT_ROOT", str(MODULE_ROOT / "sample_project"))),
            specs_dir=Path(
                _env("SDDCTX_SPECS_DIR", str(MODULE_ROOT / "samples" / "specs" / "v1"))
            ),
        )
        for key, value in overrides.items():
            if value is not None:
                setattr(settings, key, value)
        settings.prepare()
        return settings

    def prepare(self) -> "Settings":
        self.data_dir = Path(self.data_dir).resolve()
        self.project_root = Path(self.project_root).resolve()
        self.specs_dir = Path(self.specs_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self

    # ------------------------------------------------------------------ 派生路径

    @property
    def seekdb_path(self) -> Path:
        return self.data_dir / "seekdb"

    @property
    def state_dir(self) -> Path:
        return self.data_dir / "state"

    @property
    def query_log(self) -> Path:
        return self.module_root / "artifacts" / "logs" / "seekdb-queries.jsonl"

    @property
    def devlog_path(self) -> Path:
        return self.module_root / "artifacts" / "logs" / "minimax-devlog.jsonl"
