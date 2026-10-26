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

"""Rerank Memory candidates through one batched HTTP scoring service."""

from __future__ import annotations

import math

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage

HTTP_RERANK_POLICY_ID = "powercontext.memory.rerank.http.v1"
DEFAULT_BATCH_SIZE = 8


class HTTPMemoryReranker:
    """Score candidate batches over HTTP and keep one globally ordered selection."""

    policy_id = HTTP_RERANK_POLICY_ID

    def __init__(
        self,
        url: str,
        /,
        *,
        client: httpx.AsyncClient | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if not isinstance(url, str) or not url or url != url.strip():
            raise ValueError("reranker url must be a non-empty trimmed string")  # noqa: TRY003
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
            raise ValueError("reranker batch_size must be a positive integer")  # noqa: TRY003
        self._url = url
        self._client = client
        self._batch_size = batch_size

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        """Score every batch, then order the whole pool by score and coarse rank."""

        if not isinstance(query, str) or not query.strip():
            raise ValueError("rerank query must be a non-blank string")  # noqa: TRY003
        if len(candidates) < 1:
            raise ValueError("rerank requires at least one candidate")  # noqa: TRY003
        if limit < 1 or limit > len(candidates):
            raise ValueError("rerank limit must be between one and the candidate count")  # noqa: TRY003

        scores: dict[int, float] = {}
        requests = 0
        client = self._client
        owned: httpx.AsyncClient | None = None
        if client is None:
            owned = httpx.AsyncClient()
            client = owned
        try:
            for start in range(0, len(candidates), self._batch_size):
                batch = candidates[start : start + self._batch_size]
                ranks = tuple(range(start + 1, start + len(batch) + 1))
                payload = {
                    "query": query,
                    "candidates": [
                        {"rank": rank, "text": candidate.text} for rank, candidate in zip(ranks, batch, strict=True)
                    ],
                }
                response = await client.post(self._url, json=payload)
                requests += 1
                scores.update(_parse_scores(response, ranks))
        finally:
            if owned is not None:
                await owned.aclose()

        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return MemoryRerankDecision(
            selected_ranks=tuple(rank for rank, _score in ordered[:limit]),
            usage=InferenceUsage(requests=requests),
        )


def _parse_scores(response: httpx.Response, ranks: tuple[int, ...], /) -> dict[int, float]:
    if response.status_code < 200 or response.status_code >= 300:
        raise ValueError(f"reranker responded with HTTP {response.status_code}")  # noqa: TRY003
    payload = _response_payload(response)
    entries = payload["scores"]
    expected = set(ranks)
    scored: dict[int, float] = {}
    for entry in entries:
        rank, score = _score_entry(entry, expected)
        if rank in scored:
            raise ValueError(f"reranker returned duplicate rank {rank!r}")  # noqa: TRY003
        scored[rank] = score
    if set(scored) != expected:
        raise ValueError("reranker scores must cover every submitted candidate exactly once")  # noqa: TRY003
    return scored


def _response_payload(response: httpx.Response, /) -> dict[str, object]:
    try:
        payload = response.json()
    except ValueError as error:
        raise ValueError(f"reranker response is not JSON: {error}") from error  # noqa: TRY003
    if not isinstance(payload, dict) or set(payload) != {"scores"}:
        raise ValueError("reranker response must contain exactly the scores field")  # noqa: TRY003
    if not isinstance(payload["scores"], list):
        raise ValueError("reranker scores must be a list")  # noqa: TRY003, TRY004
    return payload


def _score_entry(entry: object, expected: set[int], /) -> tuple[int, float]:
    if not isinstance(entry, dict) or set(entry) != {"rank", "score"}:
        raise ValueError("reranker score entries must contain exactly rank and score")  # noqa: TRY003
    rank = entry["rank"]
    if not isinstance(rank, int) or isinstance(rank, bool) or rank not in expected:
        raise ValueError(f"reranker returned an unexpected rank {rank!r}")  # noqa: TRY003
    score = entry["score"]
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        raise ValueError(f"reranker score for rank {rank!r} must be a number")  # noqa: TRY003, TRY004
    if not math.isfinite(float(score)):
        raise ValueError(f"reranker score for rank {rank!r} must be finite")  # noqa: TRY003
    return rank, float(score)


__all__ = ["HTTPMemoryReranker"]
