# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Batched HTTP scoring adapter for Memory candidate reranking."""

from __future__ import annotations

import math

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage

HTTP_MEMORY_RERANK_POLICY_ID = "http-cross-encoder-v1"


class HTTPMemoryReranker:
    """Score candidate batches over HTTP and select one global ranking."""

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = HTTP_MEMORY_RERANK_POLICY_ID,
    ) -> None:
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")  # noqa: TRY003
        self.endpoint = endpoint
        self.batch_size = batch_size
        self.policy_id = policy_id
        self._client = client

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        """Send every global candidate rank exactly once and select globally."""

        _validate_bounds(len(candidates), limit)
        scores: dict[int, float] = {}
        requests = 0
        for start in range(0, len(candidates), self.batch_size):
            batch = candidates[start : start + self.batch_size]
            ranks = tuple(range(start + 1, start + 1 + len(batch)))
            response = await self._client.post(
                self.endpoint,
                json={
                    "query": query,
                    "candidates": [
                        {"rank": rank, "text": candidate.text}
                        for rank, candidate in zip(ranks, batch, strict=True)
                    ],
                },
            )
            requests += 1
            _raise_for_error_status(response)
            scores.update(_parse_scores(response, ranks))

        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return MemoryRerankDecision(
            selected_ranks=tuple(rank for rank, _score in ordered[:limit]),
            usage=InferenceUsage(requests=requests),
        )


def _raise_for_error_status(response: httpx.Response) -> None:
    response.raise_for_status()
    if not 200 <= response.status_code < 300:
        raise httpx.HTTPStatusError(
            f"unexpected reranker status {response.status_code}",
            request=response.request,
            response=response,
        )


def _parse_scores(response: httpx.Response, expected_ranks: tuple[int, ...]) -> dict[int, float]:
    try:
        document = response.json()
    except ValueError as error:
        raise ValueError("reranker response must be valid JSON") from error

    if not isinstance(document, dict) or set(document) != {"scores"}:
        raise ValueError("reranker response must contain exactly one 'scores' field")  # noqa: TRY003
    entries = document["scores"]
    if not isinstance(entries, list):
        raise ValueError("reranker scores must be a list")  # noqa: TRY003

    expected = set(expected_ranks)
    if len(entries) != len(expected):
        raise ValueError("reranker scores must cover every batch rank exactly once")  # noqa: TRY003

    parsed: dict[int, float] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"rank", "score"}:
            raise ValueError("each reranker score must contain exactly 'rank' and 'score'")  # noqa: TRY003
        rank = entry["rank"]
        score = entry["score"]
        if type(rank) is not int or rank not in expected or rank in parsed:
            raise ValueError("reranker scores must cover every batch rank exactly once")  # noqa: TRY003
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            raise ValueError("reranker score must be a finite number")  # noqa: TRY003
        parsed[rank] = float(score)

    if parsed.keys() != expected:
        raise ValueError("reranker scores must cover every batch rank exactly once")  # noqa: TRY003
    return parsed


def _validate_bounds(candidate_count: int, limit: int) -> None:
    if candidate_count < 1:
        raise ValueError("rerank requires at least one candidate")  # noqa: TRY003
    if limit < 1 or limit > candidate_count:
        raise ValueError("rerank limit must be between one and the candidate count")  # noqa: TRY003


__all__ = ["HTTP_MEMORY_RERANK_POLICY_ID", "HTTPMemoryReranker"]
