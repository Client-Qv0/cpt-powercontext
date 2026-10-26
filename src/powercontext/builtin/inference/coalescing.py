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

"""Coalesce concurrent Embedding work and cache successful vectors."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict

from powercontext.builtin.inference.models import EmbeddingResult, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel

DEFAULT_MAX_BATCH_SIZE = 64
DEFAULT_COALESCE_MS = 5.0
DEFAULT_CACHE_SIZE = 1024
_NONE_USAGE = InferenceUsage(requests=0)
_Completion = tuple[tuple[float, ...], int | None, InferenceUsage]


class CoalescingEmbeddingModel:
    """Share one provider request per text while preserving every caller's order."""

    def __init__(
        self,
        inner: EmbeddingModel,
        /,
        *,
        max_batch_size: int = DEFAULT_MAX_BATCH_SIZE,
        coalesce_ms: float = DEFAULT_COALESCE_MS,
        cache_size: int = DEFAULT_CACHE_SIZE,
    ) -> None:
        if not _is_positive_int(max_batch_size):
            raise ValueError("max_batch_size must be a positive integer")  # noqa: TRY003
        if not _is_number(coalesce_ms) or not math.isfinite(coalesce_ms) or coalesce_ms < 0:
            raise ValueError("coalesce_ms must be a non-negative number")  # noqa: TRY003
        if not isinstance(cache_size, int) or isinstance(cache_size, bool) or cache_size < 0:
            raise ValueError("cache_size must be a non-negative integer")  # noqa: TRY003
        self._inner = inner
        self.profile = inner.profile
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = float(coalesce_ms) / 1000
        self._cache_size = cache_size
        self._cache: OrderedDict[str, tuple[float, ...]] = OrderedDict()
        self._waiting: dict[str, asyncio.Future[_Completion]] = {}
        self._batches = 0
        self._flush_task: asyncio.Task[None] | None = None

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(vectors=())

        unique = tuple(dict.fromkeys(texts))
        claims = {text: self._claim(text) for text in unique}
        if any(text in self._waiting for text in unique):
            self._schedule_flush()
        completed = await asyncio.gather(*(asyncio.shield(claims[text]) for text in unique))
        vectors = {text: result[0] for text, result in zip(unique, completed, strict=True)}
        usages = {batch: usage for _, batch, usage in completed if batch is not None}
        return EmbeddingResult(
            vectors=tuple(vectors[text] for text in texts),
            usage=self._usage_for(list(usages.values())),
        )

    def _claim(self, text: str) -> asyncio.Future[_Completion]:
        cached = self._cache_get(text)
        if cached is not None:
            resolved: asyncio.Future[_Completion] = asyncio.get_running_loop().create_future()
            resolved.set_result((cached, None, _NONE_USAGE))
            return resolved
        waiting = self._waiting.get(text)
        if waiting is not None:
            return waiting
        pending: asyncio.Future[_Completion] = asyncio.get_running_loop().create_future()
        self._waiting[text] = pending
        return pending

    def _schedule_flush(self) -> None:
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.ensure_future(self._flush())

    async def _flush(self) -> None:
        try:
            if self._coalesce_seconds:
                await asyncio.sleep(self._coalesce_seconds)
            while self._waiting:
                texts = tuple(self._waiting)[: self._max_batch_size]
                batch = self._batches
                self._batches += 1
                await self._run_batch(texts, batch)
        finally:
            self._flush_task = None
            if self._waiting:
                self._schedule_flush()

    async def _run_batch(self, texts: tuple[str, ...], batch: int) -> None:
        waiters = tuple(self._waiting[text] for text in texts)
        try:
            result = await self._embed_batch(texts)
        except BaseException as error:
            self._abandon(texts, waiters, error)
            if isinstance(error, asyncio.CancelledError):
                raise
            return
        self._settle(texts, waiters, batch, result)

    async def _embed_batch(self, texts: tuple[str, ...]) -> EmbeddingResult:
        result = await self._inner.embed(texts)
        if len(result.vectors) != len(texts):
            raise ValueError("embedding provider must return one vector per text")  # noqa: TRY003
        return result

    def _abandon(
        self,
        texts: tuple[str, ...],
        waiters: tuple[asyncio.Future[_Completion], ...],
        error: BaseException,
    ) -> None:
        for text in texts:
            self._waiting.pop(text, None)
        for waiter in waiters:
            if waiter.done():
                continue
            if isinstance(error, asyncio.CancelledError):
                waiter.cancel()
            else:
                waiter.set_exception(error)

    def _settle(
        self,
        texts: tuple[str, ...],
        waiters: tuple[asyncio.Future[_Completion], ...],
        batch: int,
        result: EmbeddingResult,
    ) -> None:
        for text, vector, waiter in zip(texts, result.vectors, waiters, strict=True):
            self._waiting.pop(text, None)
            self._cache_put(text, vector)
            if not waiter.done():
                waiter.set_result((vector, batch, result.usage))

    def _usage_for(self, usages: list[InferenceUsage]) -> InferenceUsage:
        if not usages:
            return _NONE_USAGE
        return InferenceUsage(
            requests=sum(usage.requests for usage in usages),
            input_tokens=_sum_reported(usages, "input_tokens"),
            output_tokens=_sum_reported(usages, "output_tokens"),
        )

    def _cache_get(self, text: str) -> tuple[float, ...] | None:
        if self._cache_size == 0:
            return None
        vector = self._cache.get(text)
        if vector is not None:
            self._cache.move_to_end(text)
        return vector

    def _cache_put(self, text: str, vector: tuple[float, ...]) -> None:
        if self._cache_size == 0:
            return
        self._cache[text] = vector
        self._cache.move_to_end(text)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)


def _sum_reported(usages: list[InferenceUsage], field: str) -> int | None:
    values = [getattr(usage, field) for usage in usages]
    if any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)


def _is_positive_int(value: object, /) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _is_number(value: object, /) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


__all__ = ["CoalescingEmbeddingModel"]
