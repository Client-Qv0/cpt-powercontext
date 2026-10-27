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
from itertools import pairwise

from pydantic import BaseModel, Field
from pypdf import PdfReader

from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.runtime.models import MemoryEntryRecord, SearchMemoryRequest
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
    "reasonably",
    "healthy",
    "profile",
    "between",
    "improved",
    "improving",
    "declined",
    "relevant",
    "useful",
    "metric",
    "measure",
    "would",
    "ask",
    "about",
    "like",
    "explain",
    "why",
    "not",
    "something",
    "if",
    "then",
    "who",
    "assume",
    "you",
    "your",
    "public",
    "equities",
    "using",
    "information",
    "end",
    "able",
    "could",
    "can",
    "should",
    "there",
    "more",
    "less",
    "most",
    "whether",
    "meaningful",
    "conventional",
    "roughly",
    "over",
    "units",
    "percents",
    "round",
    "rounded",
    "one",
    "two",
    "three",
    "decimal",
    "place",
    "places",
    "line",
    "item",
    "items",
    "asked",
    "utilizing",
    "clearly",
    "address",
    "base",
    "judgments",
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
    # Enumerating the public scoped snapshot preserves every genuine citation.
    # Native FTS alone can discard a relevant issuer's pages when another issuer
    # dominates a common financial term's bounded candidate pool.
    records = tuple(record for record in (await memory.list()).entries if _page_location(record) is not None)
    records = _matching_documents(records, question)
    if not records:
        return ()
    terms = _ranking_terms(terms, records, question)
    intent, concept_terms = _financial_intent(question)
    expanded = tuple(
        dict.fromkeys(
            _stem(term)
            for term in (*terms, *(extra for term in terms for extra in _EXPANSIONS.get(term, ())), *concept_terms)
        )
    )
    native = await memory.search(SearchMemoryRequest(query=" ".join(terms[:24]), mode="fts", limit=max(40, limit * 4)))
    ranks = {(hit.entry_id, hit.entry_version_id): 1 / (60 + rank) for rank, hit in enumerate(native.hits, 1)}
    hits = {(record.entry.entry_id, record.entry.entry_version_id): record for record in records}
    counts = {
        key: Counter(_stem(term) for term in _TOKENS.findall(record.entry.text.lower())) for key, record in hits.items()
    }
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
        lexical += _heading_score(hits[key].entry.text, intent)
        return (-lexical - ranks.get(key, 0), key)

    selected = []
    pages_seen = set()
    for key in sorted(hits, key=score):
        record = hits[key]
        entry = record.entry
        page_sources = tuple(
            sorted((ref.source_type, ref.source_id) for ref in entry.sources if ref.source_type == "pdf-page")
        )
        if not page_sources or page_sources in pages_seen:
            continue
        pages_seen.add(page_sources)
        selected.append(record.citation)
        if len(selected) == limit:
            break
    return _expand_adjacent_pages(records, selected, limit)


def _heading_score(text: str, intent: set[str]) -> float:
    # A physical page may start with a preceding section's final paragraphs.
    # Recognize short heading lines across the whole page, not only its prefix.
    lines = tuple(
        " ".join(_TOKENS.findall(re.sub(r"\([^)]*\)", "", line).lower()))
        for line in text.splitlines()
        if line.strip() and len(line.strip()) <= 160
    )
    headings = (*lines, *(f"{left} {right}" for left, right in pairwise(lines)))
    prefix = r"(?:(?:condensed|consolidated|combined|unaudited) )*"
    patterns = {
        "income": prefix + r"statements? of (?:income|operations|earnings)(?: and comprehensive (?:income|loss))?",
        "cash": prefix + r"statements? of cash flows?",
        "balance": prefix + r"(?:balance sheets?|statements? of financial (?:position|condition))",
        "segment": r"(?:summary of )?(?:business )?segments?(?: (?:information|results|data))?|reportable segments",
        "business": r"our (?:business|divisions)|business overview|item \d+ business|principal products|products and services",
        "geography": r"geographic (?:operations|regions|information)|our divisions|geographical (?:areas|regions)",
    }
    return 8.0 * sum(any(re.fullmatch(patterns[kind], heading) for heading in headings) for kind in intent)


def _stem(term: str) -> str:
    if len(term) > 4 and term.endswith("ies"):
        return term[:-3] + "y"
    return term[:-1] if len(term) > 3 and term.endswith("s") and not term.endswith("ss") else term


def _ranking_terms(terms, records, question):
    compact_question = "".join(_TOKENS.findall(question.lower()))
    issuers = {
        "".join(
            _TOKENS.findall(re.split(r"(?:19|20)\d{2}", record.entry.text.partition("\n")[0], maxsplit=1)[0].lower())
        )
        for record in records
    }
    mentioned = {issuer for issuer in issuers if issuer in compact_question}
    fiscal_tokens = set(re.findall(r"\bfy\s*(\d{2,4})\b", question.lower()))
    informative = tuple(
        dict.fromkeys(
            _stem(term)
            for term in terms
            if len(term) > 1
            and term not in fiscal_tokens
            and not re.fullmatch(r"(?:19|20)\d{2}", term)
            and not any(term in issuer for issuer in mentioned)
        )
    )
    return informative or tuple(dict.fromkeys(_stem(term) for term in terms))


def _matching_documents(records: tuple[MemoryEntryRecord, ...], question: str) -> tuple[MemoryEntryRecord, ...]:
    groups = {}
    for record in records:
        location = _page_location(record)
        if location is not None:
            groups.setdefault(location[0], []).append(record)
    compact_question = "".join(_TOKENS.findall(question.lower()))
    matched = set()
    for identity, pages in groups.items():
        document_id = pages[0].entry.text.partition("\n")[0]
        issuer = re.split(r"(?:19|20)\d{2}", document_id, maxsplit=1)[0]
        issuer = "".join(_TOKENS.findall(issuer.lower()))
        if len(issuer) >= 2 and issuer in compact_question:
            matched.add(identity)
    if not matched:
        # Resolve query acronyms only from this corpus, rather than maintaining a
        # dataset-specific issuer/alias table. Ambiguous acronyms do not filter.
        acronyms = {
            token
            for token in re.findall(r"\b[A-Z][A-Za-z0-9]{1,7}\b", question)
            if sum(character.isupper() for character in token) >= 2
        } - {
            "USD",
            "EBITDA",
            "GAAP",
            "IFRS",
            "ROE",
            "ROA",
            "EPS",
            "COGS",
            "FY",
        }
        for acronym in acronyms:
            if re.fullmatch(r"FY\d+", acronym):
                continue
            owners = {
                identity
                for identity, pages in groups.items()
                if any(acronym.lower() in _TOKENS.findall(page.entry.text.lower()) for page in pages)
            }
            if len(owners) == 1:
                matched.update(owners)
    return tuple(
        record
        for record in records
        if not matched or ((location := _page_location(record)) is not None and location[0] in matched)
    )


def _financial_intent(question: str) -> tuple[set[str], tuple[str, ...]]:
    words = set(_TOKENS.findall(question.lower()))
    keywords = {
        "income": {
            "income",
            "profit",
            "margin",
            "margins",
            "revenue",
            "sales",
            "ebitda",
            "earnings",
            "tax",
            "taxes",
            "growth",
        },
        "cash": {"ebitda", "capex", "depreciation", "amortization", "dividend", "dividends"},
        "balance": {
            "quick",
            "liquidity",
            "assets",
            "liabilities",
            "liability",
            "balance",
            "inventory",
            "receivable",
            "equity",
        },
        "segment": {"category", "categories", "segment", "segments"},
        "business": {"products", "services", "geographies", "geography", "customer", "customers"},
        "geography": {"geographies", "geography", "geographic", "countries", "regions"},
    }
    kinds = {kind for kind, vocabulary in keywords.items() if words & vocabulary}
    balance_kinds, concepts = _balance_sheet_intent(words)
    kinds.update(balance_kinds)
    if re.search(r"\bcash\s*flows?\b", question.lower()):
        kinds.add("cash")
        concepts.extend(("cash", "flows", "operating", "activities"))
    if re.search(r"\bp\s*&\s*l\b|\bprofit and loss\b", question.lower()):
        kinds.add("income")
    if "growth" in words:
        concepts.extend(("revenues", "sales", "income", "earnings"))
    if "gross" in words and words & {"margin", "margins"}:
        concepts.extend(("cost", "goods", "products", "sold", "sales", "revenues", "profit"))
    if "metric" in words and words & {"useful", "relevant", "meaningful"}:
        kinds.add("business")
    if words & {"tax", "taxes"}:
        concepts.extend(("income", "tax", "pretax", "before", "benefit", "provision", "expense"))
    if words & {"category", "categories", "segment", "segments"}:
        concepts.extend(("segments", "segment", "business", "revenues", "sales"))
    if words & {"customer", "customers"}:
        concepts.extend(("clients", "government", "commercial", "principal", "concentration"))
    return kinds, tuple(concepts)


def _balance_sheet_intent(words: set[str]) -> tuple[set[str], list[str]]:
    """Map balance-sheet metrics to the underlying statement operands."""
    kinds, concepts = set(), []
    if {"working", "capital"} <= words:
        kinds.add("balance")
        concepts.extend(("current", "assets", "liabilities", "balance", "sheets"))
    if words & {"quick", "liquidity"}:
        concepts.extend(("cash", "current", "assets", "liabilities", "receivables", "inventories", "balance", "sheets"))
    if "ratio" in words and words & {"debt", "leverage", "current", "capital"}:
        kinds.add("balance")
        concepts.extend(("assets", "liabilities", "equity", "balance", "sheets"))
    if words & {"ppne", "ppe"} or {"pp", "e"} <= words:
        kinds.add("balance")
        concepts.extend(("property", "plant", "equipment", "net", "assets"))
    if {"capital", "intensive"} <= words:
        kinds.update(("balance", "income"))
        concepts.extend(("property", "plant", "equipment", "assets", "sales", "revenues"))
    if "turnover" in words and words & {"inventory", "inventories"}:
        kinds.update(("balance", "income"))
        concepts.extend(("cost", "sales", "goods", "inventories", "inventory"))
    return kinds, concepts


def _expand_adjacent_pages(records, selected, limit):
    if len(selected) <= 1 or limit < 5:
        return tuple(selected)
    location, citation_location = _page_locations(records)
    # Preserve the ranked evidence pool. The former 50% neighbor reservation
    # evicted relevant pages 11-20 even when the neighboring pages were unrelated.
    reserve = min(4, limit // 5)
    anchors = selected[: max(1, limit - reserve)]
    chosen = list(anchors)
    used = {(citation.entry_id, citation.entry_version_id) for citation in chosen}
    for citation in anchors[:2]:
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


def _page_location(record: MemoryEntryRecord) -> tuple[str, int] | None:
    references = [source for source in record.entry.sources if source.source_type == "pdf-page"]
    if len(references) != 1:
        return None
    prefix, separator, number = references[0].source_id.rpartition(":")
    return (prefix, int(number)) if separator and number.isdigit() else None
