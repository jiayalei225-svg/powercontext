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

"""Cross-call embedding request coalescing with a bounded success cache."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel

if TYPE_CHECKING:
    from powercontext.builtin.artifacts.memory.models import EmbeddingProfile


@dataclass(slots=True)
class _PendingText:
    text: str
    future: asyncio.Future[EmbeddingVector]
    batch: _PendingBatch | None = None


@dataclass(slots=True)
class _PendingBatch:
    entries: tuple[_PendingText, ...]
    usage: InferenceUsage | None = None


class CoalescingEmbeddingModel:
    """Share in-flight embedding work and cache successful vectors across callers."""

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if type(max_batch_size) is not int or max_batch_size < 1:
            raise ValueError("max_batch_size must be a positive integer")  # noqa: TRY003
        if type(cache_size) is not int or cache_size < 0:
            raise ValueError("cache_size must be a non-negative integer")  # noqa: TRY003
        if (
            isinstance(coalesce_ms, bool)
            or not isinstance(coalesce_ms, (int, float))
            or not math.isfinite(coalesce_ms)
            or coalesce_ms < 0
        ):
            raise ValueError("coalesce_ms must be a non-negative finite number")  # noqa: TRY003
        self._model = model
        self.profile: EmbeddingProfile = model.profile
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = coalesce_ms / 1000.0
        self._cache_size = cache_size
        self._cache: OrderedDict[str, EmbeddingVector] = OrderedDict()
        self._inflight: dict[str, _PendingText] = {}
        self._pending: list[_PendingText] = []
        self._wakeup = asyncio.Event()
        self._dispatcher: asyncio.Task[None] | None = None
        self._batch_tasks: set[asyncio.Task[None]] = set()

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        """Embed one ordered batch, sharing work with concurrent callers."""

        inputs = tuple(texts)
        if not inputs:
            return EmbeddingResult(vectors=(), usage=InferenceUsage(requests=0))
        unique = tuple(dict.fromkeys(inputs))
        vectors_by_text: dict[str, EmbeddingVector] = {}
        entries: list[_PendingText] = []
        created = False
        for text in unique:
            cached = self._cached(text)
            if cached is not None:
                vectors_by_text[text] = cached
                continue
            entry = self._inflight.get(text)
            if entry is None:
                entry = _PendingText(text, asyncio.get_running_loop().create_future())
                self._inflight[text] = entry
                self._pending.append(entry)
                created = True
            entries.append(entry)
        if created:
            self._ensure_dispatcher()
        if entries:
            outcomes = await asyncio.gather(
                *(asyncio.shield(entry.future) for entry in entries),
                return_exceptions=True,
            )
            usages: dict[int, InferenceUsage] = {}
            for entry, outcome in zip(entries, outcomes, strict=True):
                if isinstance(outcome, BaseException):
                    raise outcome
                vectors_by_text[entry.text] = outcome
                batch = entry.batch
                if batch is not None and batch.usage is not None:
                    usages[id(batch)] = batch.usage
        else:
            usages = {}
        return EmbeddingResult(
            vectors=tuple(vectors_by_text[text] for text in inputs),
            usage=_aggregate_usage(tuple(usages.values())),
        )

    def _cached(self, text: str) -> EmbeddingVector | None:
        if self._cache_size == 0:
            return None
        vector = self._cache.get(text)
        if vector is None:
            return None
        self._cache.move_to_end(text)
        return vector

    def _ensure_dispatcher(self) -> None:
        if self._dispatcher is None or self._dispatcher.done():
            self._dispatcher = asyncio.get_running_loop().create_task(self._dispatch())
        self._wakeup.set()

    async def _dispatch(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            while self._pending:
                if len(self._pending) >= self._max_batch_size:
                    self._launch(self._max_batch_size)
                    continue
                if self._coalesce_seconds > 0:
                    deadline = loop.time() + self._coalesce_seconds
                    while self._pending and len(self._pending) < self._max_batch_size:
                        remaining = deadline - loop.time()
                        if remaining <= 0:
                            break
                        self._wakeup.clear()
                        try:
                            await asyncio.wait_for(self._wakeup.wait(), timeout=remaining)
                        except TimeoutError:
                            break
                if self._pending:
                    self._launch(min(len(self._pending), self._max_batch_size))
        finally:
            self._dispatcher = None

    def _launch(self, count: int) -> None:
        entries = tuple(self._pending[:count])
        del self._pending[:count]
        if not entries:
            return
        batch = _PendingBatch(entries)
        for entry in entries:
            entry.batch = batch
        task = asyncio.get_running_loop().create_task(self._run_batch(batch))
        self._batch_tasks.add(task)
        task.add_done_callback(self._batch_tasks.discard)

    async def _run_batch(self, batch: _PendingBatch) -> None:
        entries = batch.entries
        try:
            result = await self._embed_batch(entries)
            batch.usage = result.usage
            for entry, vector in zip(entries, result.vectors, strict=True):
                self._remember(entry.text, vector)
                self._inflight.pop(entry.text, None)
                if not entry.future.done():
                    entry.future.set_result(vector)
        except BaseException as error:
            for entry in entries:
                self._inflight.pop(entry.text, None)
                if not entry.future.done():
                    entry.future.set_exception(error)
            if isinstance(error, asyncio.CancelledError):
                raise

    async def _embed_batch(self, entries: tuple[_PendingText, ...]) -> EmbeddingResult:
        result = await self._model.embed(tuple(entry.text for entry in entries))
        if len(result.vectors) != len(entries):
            raise ValueError("embedding model returned an unexpected vector count")  # noqa: TRY003
        return result

    def _remember(self, text: str, vector: EmbeddingVector) -> None:
        if self._cache_size == 0:
            return
        self._cache[text] = vector
        self._cache.move_to_end(text)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)


def _aggregate_usage(usages: tuple[InferenceUsage, ...]) -> InferenceUsage:
    if not usages:
        return InferenceUsage(requests=0)
    return InferenceUsage(
        requests=sum(usage.requests for usage in usages),
        input_tokens=_sum_optional(usage.input_tokens for usage in usages),
        output_tokens=_sum_optional(usage.output_tokens for usage in usages),
    )


def _sum_optional(values: Iterable[int | None]) -> int | None:
    total = 0
    seen = False
    for value in values:
        if value is not None:
            total += value
            seen = True
    return total if seen else None


__all__ = ["CoalescingEmbeddingModel"]
