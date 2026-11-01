"""Embedding backends.

The default is a local ONNX BGE model tuned for Chinese, so the demo needs no
API key. A generic OpenAI-compatible endpoint can be selected with env vars.
"""

from __future__ import annotations

import httpx

from .settings import settings

ZH_MODEL = "bge-small-zh-v1.5"
ZH_REPO = "Xenova/bge-small-zh-v1.5"
ZH_DIM = 512
MINILM_DIM = 384

_active = {"label": ZH_MODEL, "mode": "local", "dim": ZH_DIM}


class LocalBgeZh:
    """Chinese BGE-small running on onnxruntime inside pyseekdb."""

    def __init__(self) -> None:
        from pyseekdb.utils.embedding_functions import OnnxEmbeddingFunction

        self._fn = OnnxEmbeddingFunction(model_name=ZH_MODEL, hf_model_id=ZH_REPO, dimension=ZH_DIM)

    @staticmethod
    def name() -> str:
        return "paperdesk-bge-zh"

    @property
    def dimension(self) -> int:
        return ZH_DIM

    def __call__(self, documents):
        return self._fn(documents)

    def get_config(self) -> dict:
        return {"model": ZH_MODEL, "repo": ZH_REPO, "dimension": ZH_DIM}


class ApiEmbedding:
    """OpenAI-compatible /embeddings endpoint (DashScope, SiliconFlow, ...)."""

    def __init__(self, base: str, key: str, model: str, dim: int) -> None:
        self.base = base.rstrip("/")
        self.key = key
        self.model = model
        self._dim = dim

    @staticmethod
    def name() -> str:
        return "paperdesk-api"

    @property
    def dimension(self) -> int:
        return self._dim

    def __call__(self, documents):
        single = isinstance(documents, str)
        batch = [documents] if single else list(documents)
        response = httpx.post(
            f"{self.base}/embeddings",
            headers={"Authorization": f"Bearer {self.key}"},
            json={"model": self.model, "input": batch},
            timeout=60.0,
        )
        response.raise_for_status()
        rows = sorted(response.json()["data"], key=lambda row: row.get("index", 0))
        vectors = [row["embedding"] for row in rows]
        if vectors:
            self._dim = len(vectors[0])
        return vectors[0] if single else vectors

    def get_config(self) -> dict:
        return {"base": self.base, "model": self.model, "dimension": self._dim}

    @staticmethod
    def build_from_config(config: dict):
        return ApiEmbedding(config["base"], "", config["model"], config["dimension"])


def resolve():
    """Return (embedding_function, collection_suffix, label)."""
    if settings.embedding_mode == "api":
        if not (settings.embedding_base and settings.embedding_key and settings.embedding_model):
            raise RuntimeError(
                "EMBEDDING_MODE=api requires EMBEDDING_API_BASE, EMBEDDING_API_KEY and EMBEDDING_MODEL"
            )
        dim = settings.embedding_dim or 1024
        fn = ApiEmbedding(settings.embedding_base, settings.embedding_key, settings.embedding_model, dim)
        suffix = "api_" + settings.embedding_model.replace("/", "_").replace("-", "_")
        _active.update(label=settings.embedding_model, mode="api", dim=dim)
        return fn, suffix, settings.embedding_model

    try:
        fn = LocalBgeZh()
        _active.update(label=ZH_MODEL, mode="local", dim=ZH_DIM)
        return fn, "bge_zh", ZH_MODEL
    except Exception as exc:  # checkpoint unavailable -> use pyseekdb's bundled model
        print(f"[PaperDesk] local BGE unavailable ({exc}); falling back to MiniLM", flush=True)
        from pyseekdb import DefaultEmbeddingFunction

        fn = DefaultEmbeddingFunction()
        _active.update(label="all-MiniLM-L6-v2", mode="local", dim=MINILM_DIM)
        return fn, "minilm", "all-MiniLM-L6-v2"


def active_label() -> str:
    return _active["label"]
