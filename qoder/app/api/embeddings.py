"""OpenAI-compatible embedding endpoint for PowerContext.

PowerContext needs an embedding provider to build vector indexes for memory.
Instead of asking the operator for a paid API key, the StudyCoach process
reuses its own local BGE ONNX model and exposes the smallest subset of the
OpenAI embeddings contract that PowerContext's client calls.
"""

from __future__ import annotations

import time

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..config import settings
from ..seekdb import db

router = APIRouter(tags=["inference"])


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str | None = None
    dimensions: int | None = Field(default=None, ge=1)


@router.post("/v1/embeddings")
def create_embeddings(request: EmbeddingRequest) -> dict:
    texts = [request.input] if isinstance(request.input, str) else list(request.input)
    vectors = db.embed_texts([text for text in texts])
    tokens = sum(len(text) for text in texts)
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": index, "embedding": vector}
            for index, vector in enumerate(vectors)
        ],
        "model": request.model or settings.embedding_model,
        "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
        "created": int(time.time()),
    }
