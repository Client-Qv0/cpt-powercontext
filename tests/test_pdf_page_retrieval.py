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

"""PDF retrieval must retain exact evidence in a mixed-issuer scoped Memory."""

import asyncio

import pytest

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    SubmitSourceObservation,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import SourceDefinitionRegistry, manifest_for_definition, project_source_for_transport
from powercontext.sources.pdf_pages import PDF_PAGE_SOURCE_DEFINITION, PDFPageInput, search_pdf_pages
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


class PageEvidencePipeline:
    async def extract(self, request, /):
        return tuple(
            MemoryEntryInput(
                kind="source-evidence",
                text=source.projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"],
                sources=(source,),
            )
            for source in request.sources
        )


def report_page_text(document_id, number, padding):
    if number == 1:
        return (
            "Consolidated Statements of\nFinancial Position (in millions)\n"
            "Cash 40 Receivables 60 Current assets 100\n"
            "Current liabilities 20 Long-term debt 50 Total liabilities 70"
        ) + padding
    if number % 4 == 1:
        return "Financial highlights: Cash, Current assets, Current liabilities, Debt and Equity."
    ticker = ("Ticker: NsT\n" if document_id.startswith("NORTHSTAR") else "Ticker: SrG\n") if number == 24 else ""
    return ticker + "North Star is a healthy company with the largest service profile. " * 8


@pytest.mark.parametrize(
    "question",
    [
        "Does North Star have a healthy quick ratio in FY24?",
        "What is the largest liability in North Star's balance sheet for 2024?",
        "Does NsT have positive working capital based on FY24 data?",
    ],
)
@pytest.mark.parametrize("padding", ["", " reconciliation" * 800], ids=["ordinary-page", "dense-page"])
@pytest.mark.parametrize("limit", [3, 4, 20])
def test_company_name_does_not_displace_its_financial_evidence(tmp_path, question, padding, limit):
    async def scenario():
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'pages.db'}"))
        registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
        observations = []
        for document_id in ("NORTHSTAR_2024_10K", "SOUTHRIDGE_2024_10K"):
            for number in range(1, 25):
                text = report_page_text(document_id, number, padding)
                page = PDFPageInput(document_id=document_id, document_sha256="a" * 64, page_number=number, text=text)
                observations.append(project_source_for_transport(registry, await registry.resolve(page)))
        expected_source = observations[0].name
        northstar_sources = {source.name for source in observations[:24]}
        async with open_builtin_runtime(config) as runtime:
            assert runtime.scopes is not None
            scope = await runtime.scopes.create(ScopeDraft(title="Reports", summary="PDF", idempotency_key="reports"))
            await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
            for observation in observations:
                await runtime.ingestion.submit(
                    SubmitSourceObservation(scope_id=scope.scope_id, observation=observation)
                )
        async with open_builtin_runtime(config, candidate_pipeline=PageEvidencePipeline()) as runtime:
            memory = runtime.memory.for_scope(scope.scope_id)
            while (await memory.flush()).processed:
                pass
        # Reopening and dereferencing through public APIs verifies durable exact
        # citations; the implementation never receives these expected page IDs.
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope.scope_id)
            citations = await search_pdf_pages(memory, question, limit=limit)
            sources = []
            for citation in citations:
                entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
                if padding and any(source.source_id == expected_source for source in entry.sources):
                    assert entry.text.endswith(padding)
                sources.extend(source.source_id for source in entry.sources)
            assert 1 <= len(citations) <= limit
            assert len(set(sources)) == len(sources)
            assert expected_source in sources
            assert set(sources) <= northstar_sources

    asyncio.run(scenario())
