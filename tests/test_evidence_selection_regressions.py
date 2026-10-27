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

"""Protect literal evidence selection under entity ambiguity and byte limits."""

import asyncio
import json

import pytest

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    PrepareContextRequest,
    RememberMemoryRequest,
    SearchMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.prepared_context import PreparedContextBuilder, PreparedMemoryCandidates
from powercontext.builtin.scope import ScopeDraft


async def select_from_memory(documents, query, budget):
    async with open_builtin_runtime(BuiltinConfig()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(ScopeDraft(title="Evidence", summary="Literal", idempotency_key="evidence"))
        memory = runtime.memory.for_scope(scope.scope_id)
        for text in documents:
            await memory.remember(RememberMemoryRequest(entries=(MemoryEntryInput(kind="document", text=text),)))
        page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=16))
        result = PreparedContextBuilder().build_scopes_result(
            request=PrepareContextRequest(query=query, max_bytes=budget, evidence_selection=True),
            current_scope_id=scope.scope_id,
            memory_candidates=(
                PreparedMemoryCandidates(scope_id=scope.scope_id, memory_ref=page.memory_ref, hits=page.hits),
            ),
        )
        content = result.context.content or ""
        assert result.context.content_bytes == len(content.encode("utf-8")) <= budget
        assert result.fragments
        items = json.loads(content.splitlines()[-2])["items"]
        selected = []
        for fragment, origin, item in zip(result.fragments, result.origins, items, strict=True):
            assert origin == fragment.address
            assert fragment.address.memory.scope_id == scope.scope_id
            entry = (
                await memory.get(
                    GetMemoryEntryRequest(
                        citation=MemoryCitation(
                            memory_ref=fragment.address.memory.artifact,
                            entry_id=fragment.address.entry_id,
                            entry_version_id=fragment.address.entry_version_id,
                        )
                    )
                )
            ).entry
            assert entry.text in documents
            assert fragment.text == entry.text[fragment.start : fragment.end] == item["content"]
            assert (item["start"], item["end"]) == (fragment.start, fragment.end)
            assert item["citation"]["scope_id"] == scope.scope_id
            selected.append((entry.text, fragment.start, fragment.end))
        return selected


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("budget", [1000, 1400])
def test_query_entity_outweighs_generic_verb_overlap(reverse, budget):
    relevant = (
        "XQ17 forms a complex with the amber enzyme by direct interaction. "
        "Most importantly, XQ17 accelerates the processing of cobalt RNA in enzyme-containing samples."
    )
    decoy = (
        "The amber enzyme can efficiently cleave cobalt RNA. "
        "The amber enzyme binds cobalt RNA during cleavage and releases the products afterward."
    )
    documents = (decoy, relevant) if reverse else (relevant, decoy)
    selected = asyncio.run(select_from_memory(documents, "XQ17 binds the amber enzyme to cleave cobalt RNA.", budget))
    assert any(text == relevant for text, _, _ in selected)


@pytest.mark.parametrize("budget", [1000, 1400, 1800])
def test_literal_evidence_retains_internal_sentence_whitespace(budget):
    evidence = " \nThe cobalt sensor is calibrated at 37 degrees.   \n"
    text = (
        'Reference calibration: 温度 "sensor" 🌡️. ' + evidence + "Administrative bookkeeping " + "neutral " * 180 + "."
    )
    selected = asyncio.run(select_from_memory((text,), "cobalt sensor calibrated", budget))
    start = text.index(evidence)
    assert any(left <= start and right >= start + len(evidence) for _, left, right in selected)
