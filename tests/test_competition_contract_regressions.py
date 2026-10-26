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


"""Regressions for the competition's public product contracts."""

import asyncio
import json

import pytest

from powercontext.builtin.artifacts.memory import EmbeddingProfile
from powercontext.builtin.inference import EmbeddingResult, InferenceUsage
from powercontext.builtin.inference.coalescing import CoalescingEmbeddingModel
from powercontext.builtin.runtime.context_pack import (
    ContextPack,
    ContextPackDelta,
    ContextPackError,
    apply_context_pack_delta,
)
from powercontext.sources.pi_session import PiSessionInput, parse_pi_session


def test_embedding_retains_provider_request_counts_per_shared_batch():
    class Metered:
        profile = EmbeddingProfile(profile_id="metered-regression", model="offline", dimension=1)

        async def embed(self, texts):
            return EmbeddingResult(
                vectors=tuple((1.0,) for _ in texts),
                usage=InferenceUsage(requests=3, input_tokens=7, output_tokens=2),
            )

    async def scenario():
        model = CoalescingEmbeddingModel(Metered(), max_batch_size=1, coalesce_ms=0)
        first, second = await asyncio.gather(model.embed(("a", "b", "a")), model.embed(("a",)))
        assert first.usage == InferenceUsage(requests=6, input_tokens=14, output_tokens=4)
        assert second.usage == InferenceUsage(requests=3, input_tokens=7, output_tokens=2)
        assert (await model.embed(("a",))).usage.requests == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("prefix", [-1, True, 1.0])
def test_delta_objects_reject_invalid_prefix_without_wire_round_trip(prefix):
    base = ContextPack.build((b"one", b"two"))
    kept = 1 if prefix in (-1, True, 1.0) else 0
    target = ContextPack.build(base.items[:kept])
    delta = ContextPackDelta(base.digest, target.digest, prefix, ())
    with pytest.raises(ContextPackError):
        apply_context_pack_delta(base, delta)


def test_pi_custom_message_preserves_string_content():
    records = [
        {"type": "session", "version": 3, "id": "string-message"},
        {"type": "custom_message", "id": "note", "parentId": None, "content": "原始备注"},
    ]
    raw = "\n".join(json.dumps(record, ensure_ascii=False) for record in records).encode()
    events = parse_pi_session(PiSessionInput(content=raw))
    assert len(events) == 1
    assert events[0].content == "custom: 原始备注"
    assert events[0].record == records[1]


def test_failed_embedding_batch_does_not_abort_independent_texts():
    class Partial:
        profile = EmbeddingProfile(profile_id="partial-regression", model="offline", dimension=1)

        async def embed(self, texts):
            if texts == ("bad",):
                raise RuntimeError("temporary provider failure")  # noqa: TRY003
            return EmbeddingResult(vectors=tuple((1.0,) for _ in texts), usage=InferenceUsage(requests=2))

    async def scenario():
        model = CoalescingEmbeddingModel(Partial(), max_batch_size=1, coalesce_ms=0, cache_size=0)
        failed, survived = await asyncio.gather(model.embed(("bad",)), model.embed(("good",)), return_exceptions=True)
        assert isinstance(failed, RuntimeError)
        assert survived.vectors == ((1.0,),)
        assert survived.usage.requests == 2

    asyncio.run(scenario())


def test_embedding_usage_belongs_to_the_waited_batch_after_text_is_resubmitted():
    class Repeated:
        profile = EmbeddingProfile(profile_id="resubmission-regression", model="offline", dimension=1)

        def __init__(self):
            self.calls = 0
            self.blocked = asyncio.Event()
            self.release = asyncio.Event()

        async def embed(self, texts):
            self.calls += 1
            number = self.calls
            if texts == ("b",):
                self.blocked.set()
                await self.release.wait()
            return EmbeddingResult(vectors=((float(number),),), usage=InferenceUsage(requests=number))

    async def scenario():
        provider = Repeated()
        model = CoalescingEmbeddingModel(provider, max_batch_size=1, coalesce_ms=0, cache_size=0)
        original = asyncio.create_task(model.embed(("a", "b")))
        await provider.blocked.wait()
        repeated = asyncio.create_task(model.embed(("a",)))
        await asyncio.sleep(0)
        provider.release.set()
        first, second = await asyncio.gather(original, repeated)
        assert first.usage.requests == 3
        assert first.vectors == ((1.0,), (2.0,))
        assert second.usage.requests == 3
        assert second.vectors == ((3.0,),)

    asyncio.run(scenario())


def test_lifecycle_replay_completes_interrupted_native_propagation(tmp_path, monkeypatch):
    from powercontext.builtin.artifacts.memory import MemoryEntryInput, MemoryService
    from powercontext.builtin.persistence.sqlite import SQLiteConfig
    from powercontext.builtin.runtime import BuiltinConfig, CaptureSource, RememberMemoryRequest, open_builtin_runtime
    from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleEvent
    from powercontext.builtin.scope import ScopeDraft

    async def scenario():
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'retry.db'}"))
        async with open_builtin_runtime(config) as runtime:
            assert runtime.scopes is not None
            scope = (
                await runtime.scopes.create(
                    ScopeDraft(title="Retry", summary="Evidence recovery", idempotency_key="retry")
                )
            ).scope_id
            service = runtime.lifecycle.for_scope(scope)
            source = await runtime.sources.for_scope(scope).capture(
                CaptureSource(source_id="root", content="Evidence", metadata={})
            )
            await service.register_source("root", source.source_ref, revision=1)
            for node in ("first", "second"):
                memory = await runtime.memory.for_scope(scope).remember(
                    RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=node),))
                )
                assert memory.entry is not None
                await service.register_memory(node, memory.entry.citation, parents=("root",), policy="all")
            original = MemoryService.forget
            calls = 0

            async def interrupted(self, *args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError("simulated interruption")  # noqa: TRY003
                return await original(self, *args, **kwargs)

            event = SourceLifecycleEvent(node_id="root", revision=1, sequence=1, available=False, reason="withdraw")
            with monkeypatch.context() as patch:
                patch.setattr(MemoryService, "forget", interrupted)
                with pytest.raises(RuntimeError):
                    await service.apply(event)
        async with open_builtin_runtime(config) as runtime:
            service = runtime.lifecycle.for_scope(scope)
            assert await service.apply(event) == []
            page = await runtime.memory.for_scope(scope).list(include_inactive=True)
            assert all(entry.state == "inactive" for entry in page.entries)
            before = page.memory_ref
            await service.apply(event)
            assert (await runtime.memory.for_scope(scope).list(include_inactive=True)).memory_ref == before

    asyncio.run(scenario())
