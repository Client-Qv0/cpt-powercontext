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


"""Capture every physical PDF page and retrieve exact persisted page citations."""

import hashlib
import io
import math
import re
from collections import Counter

from pydantic import BaseModel, Field
from pypdf import PdfReader

from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.runtime.models import SearchMemoryRequest
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    AdapterSourceDefinition,
    Source,
    SourceMaterialization,
    TextEvidence,
)


class PDFDocumentInput(BaseModel):
    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    document_id: str = Field(min_length=1)
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: int = Field(gt=0, strict=True)
    text: str


class PDFPageSource(Source):
    document_id: str
    document_sha256: str
    page_number: int
    text: str


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    if not value.document_id.strip():
        raise ValueError("document_id must not be blank")  # noqa: TRY003
    if not value.content or not value.content.startswith(b"%PDF-"):
        raise ValueError("expected complete PDF bytes")  # noqa: TRY003
    digest = hashlib.sha256(value.content).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(value.content), strict=True)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a password")  # noqa: TRY003, TRY301
        return tuple(
            PDFPageInput(
                document_id=value.document_id,
                document_sha256=digest,
                page_number=number,
                text=page.extract_text() or "",
            )
            for number, page in enumerate(reader.pages, 1)
        )
    except Exception as error:
        raise ValueError("PDF could not be parsed completely") from error  # noqa: TRY003


class PDFPageAdapter:
    name = "pdf-page"
    input_class = PDFPageInput
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        if not value.document_id.strip():
            raise ValueError("document_id must not be blank")  # noqa: TRY003
        document_key = hashlib.sha256(value.document_id.encode("utf-8")).hexdigest()
        return PDFPageSource(
            name=f"pdf:{document_key}:{value.document_sha256}:{value.page_number}",
            materialization=SourceMaterialization.CAPTURED,
            **value.model_dump(),
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(**source.model_dump(include=PDFPageInput.model_fields.keys()))


class PDFPageProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type="pdf-page",
            source_id=source.name,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(PDFPageAdapter(), version="1", projections=(PDFPageProjection(),))

_TOKENS = re.compile(r"[a-z]+|\d+")
_STOP = frozenset([
    "a",
    "an",
    "the",
    "of",
    "to",
    "in",
    "on",
    "at",
    "for",
    "by",
    "with",
    "from",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "that",
    "this",
    "these",
    "those",
    "it",
    "its",
    "and",
    "or",
    "but",
    "than",
    "which",
    "what",
    "how",
    "much",
    "many",
    "did",
    "does",
    "do",
    "has",
    "have",
    "had",
    "during",
    "according",
    "company",
    "fiscal",
    "year",
    "years",
    "annual",
    "report",
    "financial",
    "statements",
    "consolidated",
    "statement",
    "calculate",
    "please",
    "give",
    "provide",
    "percentage",
    "percent",
    "change",
    "increase",
    "decrease",
    "amount",
    "value",
])
_EXPANSIONS = {
    "revenue": ("sales", "revenues"),
    "revenues": ("sales", "revenue"),
    "profit": ("income", "earnings"),
    "earnings": ("income", "profit"),
    "capex": ("capital", "expenditures", "property", "equipment"),
    "liquidity": ("cash", "current", "assets", "liabilities"),
    "debt": ("borrowings", "obligations"),
    "dividend": ("dividends",),
    "ebitda": ("operating", "profit", "income", "depreciation", "amortization", "cash", "flows"),
    "income": ("profit", "earnings"),
    "operating": ("operations", "profit"),
    "geography": ("geographic", "segments", "divisions", "countries"),
    "geographies": ("geographic", "segments", "divisions", "countries"),
    "operates": ("operations", "business", "divisions"),
    "legal": ("litigation", "proceedings", "contingencies", "lawsuits"),
    "lawsuits": ("litigation", "proceedings", "contingencies"),
    "restructuring": ("charges", "expenses", "costs"),
    "acquisitions": ("purchase", "goodwill", "business", "combinations"),
    "pension": ("retirement", "benefits", "obligations"),
    "inventory": ("inventories",),
}
_QUESTION_WORDS = frozenset([
    "fy",
    "any",
    "primarily",
    "important",
    "ongoing",
    "directly",
    "outlined",
    "explicitly",
    "state",
    "then",
    "answer",
    "respond",
    "response",
    "question",
    "define",
    "defined",
    "assuming",
    "perspective",
    "investment",
    "analyst",
    "only",
    "use",
    "details",
    "shown",
    "within",
    "relying",
    "reported",
    "unadjusted",
    "adjusted",
    "usd",
    "millions",
    "billion",
    "billions",
    "based",
    "following",
    "respective",
    "respective",
    "total",
])


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    if not isinstance(question, str) or not question.strip() or type(limit) is not int or limit < 1:
        raise ValueError("question must be nonblank and limit must be a positive integer")  # noqa: TRY003
    terms = tuple(
        dict.fromkeys(
            token for token in _TOKENS.findall(question.lower()) if token not in _STOP and token not in _QUESTION_WORDS
        )
    )
    if not terms:
        return ()
    expanded = tuple(dict.fromkeys((*terms, *(extra for term in terms for extra in _EXPANSIONS.get(term, ())))))
    # Query short lexical groups so long natural-language questions do not fail
    # admission because a page omits conversational words from the question.
    queries = [" ".join(expanded[:16])]
    queries.extend(" ".join(expanded[start : start + 3]) for start in range(0, min(len(expanded), 30), 3))
    queries.extend(expanded[:32])
    hits, ranks = await _gather_candidates(memory, queries, limit)
    if not hits:
        return ()
    counts = {key: Counter(_TOKENS.findall(hit.text.lower())) for key, hit in hits.items()}
    frequency = Counter(token for count in counts.values() for token in count)
    average = sum(sum(count.values()) for count in counts.values()) / len(counts)
    weights = {term: 1.0 if term in terms else 0.7 for term in expanded}

    def score(key):
        count = counts[key]
        length = sum(count.values())
        lexical = sum(
            weights[term]
            * math.log(1 + (len(counts) - frequency[term] + 0.5) / (frequency[term] + 0.5))
            * count[term]
            * 2.2
            / (count[term] + 1.2 * (0.25 + 0.75 * length / max(1, average)))
            for term in weights
            if count[term]
        )
        heading = " ".join(_TOKENS.findall(hits[key].text[:650].lower()))
        if set(terms) & {"ebitda", "income", "profit", "margin", "revenue", "sales"} and re.search(
            r"statements? of (?:income|operations|earnings)", heading
        ):
            lexical += 8
        if set(expanded) & {"cash", "capex", "depreciation", "amortization"} and re.search(
            r"statements? of cash flows", heading
        ):
            lexical += 8
        return (-lexical - ranks[key], key)

    selected = []
    pages_seen = set()
    # Every returned identity originates in public scoped Memory search. Distinct
    # native Source identities preserve PDF revisions and physical page numbers.
    from powercontext.builtin.runtime.models import GetMemoryEntryRequest

    for key in sorted(hits, key=score):
        hit = hits[key]
        citation = MemoryCitation(
            memory_ref=hit.memory_ref, entry_id=hit.entry_id, entry_version_id=hit.entry_version_id
        )
        entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
        page_sources = tuple(
            sorted((ref.source_type, ref.source_id) for ref in entry.sources if ref.source_type == "pdf-page")
        )
        if not page_sources or page_sources in pages_seen:
            continue
        pages_seen.add(page_sources)
        selected.append(citation)
        if len(selected) == limit:
            break
    return await _expand_adjacent_pages(memory, selected, limit)


async def _gather_candidates(memory, queries, limit):
    hits = {}
    ranks = Counter()
    for query in dict.fromkeys(queries):
        page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=max(40, limit * 4)))
        for rank, hit in enumerate(page.hits, 1):
            key = (hit.memory_ref.artifact_id, hit.entry_id, hit.entry_version_id)
            hits[key] = hit
            ranks[key] += 1 / (60 + rank)
    return hits, ranks


async def _expand_adjacent_pages(memory, selected, limit):
    if len(selected) <= 1 or limit < 4:
        return tuple(selected)
    records = (await memory.list()).entries
    location, citation_location = _page_locations(records)
    anchors = selected[: max(1, limit // 2)]
    chosen = list(anchors)
    used = {(citation.entry_id, citation.entry_version_id) for citation in chosen}
    for citation in anchors[:5]:
        origin = citation_location.get((citation.entry_id, citation.entry_version_id))
        if origin is None:
            continue
        for offset in (-1, 1):
            neighbor = location.get((origin[0], origin[1] + offset))
            if neighbor is not None and (neighbor.entry_id, neighbor.entry_version_id) not in used:
                chosen.append(neighbor)
                used.add((neighbor.entry_id, neighbor.entry_version_id))
                if len(chosen) == limit:
                    return tuple(chosen)
    for citation in selected:
        if (citation.entry_id, citation.entry_version_id) not in used:
            chosen.append(citation)
            used.add((citation.entry_id, citation.entry_version_id))
            if len(chosen) == limit:
                break
    return tuple(chosen)


def _page_locations(records):
    location = {}
    citation_location = {}
    for record in records:
        for source in record.entry.sources:
            if source.source_type != "pdf-page":
                continue
            prefix, separator, number = source.source_id.rpartition(":")
            if separator and number.isdigit():
                key = (prefix, int(number))
                location[key] = record.citation
                citation_location[(record.citation.entry_id, record.citation.entry_version_id)] = key
    return location, citation_location
