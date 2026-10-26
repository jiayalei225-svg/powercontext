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

"""Batched reranking through an external HTTP scoring service."""

from __future__ import annotations

import math

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import (
    MemoryRerankDecision,
    _validate_bounds,
)
from powercontext.builtin.inference import InferenceUsage

_RESPONSE_FIELDS = frozenset({"scores"})
_SCORE_FIELDS = frozenset({"rank", "score"})


class HTTPMemoryReranker:
    """Score one candidate pool in bounded batches and select a global top list.

    Ranks are assigned once over the complete input and never renumbered per batch, so a
    score always maps back to the original :class:`MemoryHit`. The caller owns the client
    lifecycle; this adapter never creates or closes one.
    """

    policy_id = "http-cross-encoder-v1"

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = "http-cross-encoder-v1",
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least one")  # noqa: TRY003
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        """Request every candidate exactly once, then select from the complete pool."""

        _validate_bounds(len(candidates), limit)
        scores: dict[int, int | float] = {}
        requests = 0
        for start in range(0, len(candidates), self._batch_size):
            batch = candidates[start : start + self._batch_size]
            first_rank = start + 1
            expected_ranks = frozenset(range(first_rank, first_rank + len(batch)))
            response = await self._client.post(
                self._endpoint,
                json={
                    "query": query,
                    "candidates": [
                        {"rank": first_rank + offset, "text": candidate.text} for offset, candidate in enumerate(batch)
                    ],
                },
            )
            requests += 1
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as error:
                raise ValueError("rerank response is not valid JSON") from error  # noqa: TRY003
            scores.update(_parse_batch_scores(payload, expected_ranks))
        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return MemoryRerankDecision(
            selected_ranks=tuple(rank for rank, _score in ordered[:limit]),
            usage=InferenceUsage(requests=requests),
        )


def _parse_batch_scores(payload: object, expected_ranks: frozenset[int]) -> dict[int, int | float]:
    """Validate one batch response and return its rank-to-score mapping."""

    if not isinstance(payload, dict) or set(payload) != _RESPONSE_FIELDS:
        raise ValueError("rerank response must contain exactly 'scores'")  # noqa: TRY003
    records = payload["scores"]
    if not isinstance(records, list):
        raise ValueError("rerank response 'scores' must be a list")  # noqa: TRY003, TRY004
    scores: dict[int, int | float] = {}
    for record in records:
        rank, score = _parse_score(record, expected_ranks)
        if rank in scores:
            raise ValueError("rerank response contains duplicate ranks")  # noqa: TRY003
        scores[rank] = score
    if set(scores) != expected_ranks:
        raise ValueError("rerank response must cover every batch rank exactly once")  # noqa: TRY003
    return scores


def _parse_score(record: object, expected_ranks: frozenset[int]) -> tuple[int, int | float]:
    """Validate one score record against the batch that produced it."""

    if not isinstance(record, dict) or set(record) != _SCORE_FIELDS:
        raise ValueError("rerank score must contain exactly 'rank' and 'score'")  # noqa: TRY003
    rank = record["rank"]
    raw_score = record["score"]
    if type(rank) is not int or rank not in expected_ranks:
        raise ValueError("rerank score rank is not part of this batch")  # noqa: TRY003
    if type(raw_score) is int:
        return rank, raw_score
    if type(raw_score) is not float or not math.isfinite(raw_score):
        raise ValueError("rerank score must be a finite number")  # noqa: TRY003
    return rank, raw_score


__all__ = ["HTTPMemoryReranker"]
