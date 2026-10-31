"""Embedding providers.

Default is a fully local ONNX model so the app runs with no API key. The
bundled default is a Chinese-tuned BGE model; if its checkpoint cannot be
fetched, we fall back to the English MiniLM that ships with pyseekdb. Users who
want stronger semantics can point this at any OpenAI-compatible endpoint.
"""

from __future__ import annotations

import httpx

from .config import settings

ZH_MODEL = "bge-small-zh-v1.5"
ZH_HF_ID = "Xenova/bge-small-zh-v1.5"
ZH_DIM = 512
MINILM_DIM = 384

_active = {"model": "", "dim": 0, "mode": settings.embedding_mode}


class LocalZhEmbedding:
    """Chinese-tuned BGE small model running on onnxruntime, no network at query time."""

    def __init__(self) -> None:
        from pyseekdb.utils.embedding_functions import OnnxEmbeddingFunction

        self._backend = OnnxEmbeddingFunction(
            model_name=ZH_MODEL, hf_model_id=ZH_HF_ID, dimension=ZH_DIM
        )

    @staticmethod
    def name() -> str:
        return "paperdesk-local-zh"

    @property
    def dimension(self) -> int:
        return ZH_DIM

    def __call__(self, documents):
        return self._backend(documents)

    def get_config(self):
        return {"model": ZH_MODEL, "dimension": ZH_DIM}


class RemoteEmbeddingFunction:
    """OpenAI-compatible embedding endpoint (DashScope, SiliconFlow, OpenAI, ...)."""

    def __init__(self, base: str, api_key: str, model: str, dimension: int) -> None:
        self.base = base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._dimension = dimension

    @staticmethod
    def name() -> str:
        return "paperdesk-remote"

    @property
    def dimension(self) -> int:
        return self._dimension

    def __call__(self, documents):
        single = isinstance(documents, str)
        batch = [documents] if single else list(documents)
        response = httpx.post(
            f"{self.base}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": batch},
            timeout=60.0,
        )
        response.raise_for_status()
        payload = response.json()["data"]
        vectors = [item["embedding"] for item in sorted(payload, key=lambda item: item.get("index", 0))]
        if vectors and len(vectors[0]) != self._dimension:
            self._dimension = len(vectors[0])
        return vectors[0] if single else vectors

    def get_config(self):
        return {"base": self.base, "model": self.model, "dimension": self._dimension}

    @staticmethod
    def build_from_config(config):
        return RemoteEmbeddingFunction(config["base"], "", config["model"], config["dimension"])


def build_embedding_function():
    """Return (embedding_function, collection_suffix) for the configured mode."""
    if settings.embedding_mode == "api":
        if not (settings.embedding_api_base and settings.embedding_api_key and settings.embedding_model):
            raise RuntimeError(
                "EMBEDDING_MODE=api 需要同时配置 EMBEDDING_API_BASE、EMBEDDING_API_KEY、EMBEDDING_MODEL"
            )
        dim = settings.embedding_dim or 1024
        fn = RemoteEmbeddingFunction(
            settings.embedding_api_base, settings.embedding_api_key, settings.embedding_model, dim
        )
        _active.update(model=settings.embedding_model, dim=dim, mode="api")
        return fn, f"api_{settings.embedding_model.replace('/', '_')}"

    try:
        fn = LocalZhEmbedding()
        _active.update(model=ZH_MODEL, dim=ZH_DIM, mode="local")
        return fn, "local_zh"
    except Exception:
        from pyseekdb import DefaultEmbeddingFunction

        _active.update(model="all-MiniLM-L6-v2", dim=MINILM_DIM, mode="local")
        return DefaultEmbeddingFunction(), "local_minilm"


def embedding_signature() -> str:
    return _active["model"] or ("api" if settings.embedding_mode == "api" else ZH_MODEL)
