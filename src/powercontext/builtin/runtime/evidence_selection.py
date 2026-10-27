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


"""Select literal, query-related sentences within the complete wire budget."""

import json
import math
import re
from collections import Counter
from dataclasses import dataclass

from powercontext.artifacts import ArtifactAddress
from powercontext.builtin.runtime.models import PreparedContext
from powercontext.builtin.runtime.prepared_context import (
    MemoryEntryAddress,
    PreparedContextBuild,
    PreparedEvidenceFragment,
)
from powercontext.builtin.runtime.prepared_text import TRUST_POLICY

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
    "being",
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
    "then",
    "which",
    "who",
    "when",
    "where",
    "can",
    "could",
    "will",
    "would",
    "may",
    "might",
    "do",
    "does",
    "did",
    "has",
    "have",
    "had",
    "not",
    "no",
    "into",
    "through",
    "between",
    "during",
    "using",
    "used",
    "study",
    "studies",
    "result",
    "results",
    "show",
    "showed",
    "found",
    "suggest",
    "suggests",
    "after",
    "before",
    "also",
    "we",
    "our",
    "their",
    "they",
    "them",
    "there",
    "each",
    "both",
    "while",
    "over",
    "under",
    "more",
    "less",
    "other",
    "following",
    "compared",
    "however",
    "therefore",
    "total",
    "only",
    "respectively",
])
_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")
_CONCEPTS = {
    term: canonical
    for canonical, variants in (
        ("cancer", ("cancer", "cancers", "carcinoma", "carcinomas", "tumor", "tumors", "tumour", "tumours")),
        ("outcome", ("outcome", "outcomes", "prognosis", "prognostic")),
        ("growth", ("growth", "growing", "proliferation", "proliferative")),
        ("interaction", ("bind", "binds", "binding", "bound", "interact", "interacts", "interaction", "interactions")),
        ("cleavage", ("cleave", "cleaves", "cleaved", "cleaving", "cleavage")),
        (
            "association",
            ("associate", "associated", "association", "correlate", "correlated", "correlates", "correlation"),
        ),
        ("mirna", ("mirna", "mirnas", "microrna", "micrornas")),
        ("mortality", ("mortality", "death", "deaths")),
        ("increase", ("increase", "increases", "increased", "increasing", "elevated", "higher", "enhanced")),
        ("decrease", ("decrease", "decreases", "decreased", "decreasing", "reduce", "reduces", "reduced", "lower")),
    )
    for term in variants
}


def _terms(text):
    terms = []
    for term in _WORDS.findall(text.casefold()):
        term = _CONCEPTS.get(term, term)
        if term in _STOP:
            continue
        if len(term) > 5 and term.endswith("ies"):
            term = term[:-3] + "y"
        elif len(term) > 5 and term.endswith("ing"):
            term = term[:-3]
        elif len(term) > 4 and term.endswith("s") and not term.endswith("ss"):
            term = term[:-1]
        terms.append(term)
    return terms


@dataclass(frozen=True)
class _Sentence:
    fragment: PreparedEvidenceFragment
    terms: tuple[str, ...]
    score: float = 0


def _sentences(group):
    for hit in group.hits:
        address = MemoryEntryAddress(
            memory=ArtifactAddress(scope_id=group.scope_id, artifact=hit.memory_ref),
            entry_id=hit.entry_id,
            entry_version_id=hit.entry_version_id,
        )
        start = 0
        seen = set()
        for boundary in (*_BREAK.finditer(hit.text), None):
            end = len(hit.text) if boundary is None else boundary.end()
            text = hit.text[start:end]
            if text.strip() and text.strip() not in seen:
                seen.add(text.strip())
                yield _Sentence(PreparedEvidenceFragment(address, start, end, text), tuple(_terms(text)))
            if boundary is not None:
                start = boundary.end()


def _render(fragments):
    items = [
        {
            "citation": {
                "scope_id": fragment.address.memory.scope_id,
                "memory_ref": fragment.address.memory.artifact.model_dump(mode="json"),
                "entry_id": fragment.address.entry_id,
                "entry_version_id": fragment.address.entry_version_id,
            },
            "content": fragment.text,
            "start": fragment.start,
            "end": fragment.end,
        }
        for fragment in fragments
    ]
    body = json.dumps({"trust": "untrusted_history", "items": items}, ensure_ascii=False, separators=(",", ":"))
    return f"{TRUST_POLICY}\n\nBEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n{body}\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1"


def _merge(selected, originals):
    groups = {}
    for sentence in selected:
        fragment = sentence.fragment
        original = originals[_key(fragment.address)]
        start = fragment.start
        while start > 0 and original[start - 1].isspace():
            start -= 1
        fragment = PreparedEvidenceFragment(fragment.address, start, fragment.end, original[start : fragment.end])
        groups.setdefault(_key(fragment.address), []).append(fragment)
    merged = []
    for key, spans in groups.items():
        address = spans[0].address
        text = originals[key]
        current = None
        for span in sorted(spans, key=lambda item: item.start):
            if current is not None and (
                span.start <= current.end
                or not text[current.end : span.start].strip()
                or _joined_is_smaller(current, span, text)
            ):
                end = max(current.end, span.end)
                current = PreparedEvidenceFragment(address, current.start, end, text[current.start : end])
            else:
                if current is not None:
                    merged.append(current)
                current = span
        if current is not None:
            merged.append(current)
    return tuple(merged)


def _joined_is_smaller(first, last, original):
    """A short literal gap can cost less than repeating the complete citation."""
    joined = PreparedEvidenceFragment(first.address, first.start, last.end, original[first.start : last.end])
    return len(_render((joined,)).encode("utf-8")) <= len(_render((first, last)).encode("utf-8"))


def _key(address):
    return (
        address.memory.scope_id,
        address.memory.artifact.artifact_id,
        address.memory.artifact.revision,
        address.entry_id,
        address.entry_version_id,
    )


def select_evidence(request, groups):
    sentences = [sentence for group in groups for sentence in _sentences(group)]
    query = set(_terms(request.query))
    entities = {
        term
        for word in _WORDS.findall(request.query)
        if sum(character.isupper() for character in word) >= 2
        or (any(character.isdigit() for character in word) and any(character.isalpha() for character in word))
        for term in _terms(word)
    }
    originals = {
        _key(
            MemoryEntryAddress(
                ArtifactAddress(scope_id=group.scope_id, artifact=hit.memory_ref), hit.entry_id, hit.entry_version_id
            )
        ): hit.text
        for group in groups
        for hit in group.hits
    }
    scored = _score_candidates(sentences, query, originals, entities)
    # A small bounded beam trades citation overhead against evidence coverage. All
    # states contain literal spans; every candidate is measured after serialization.
    states = [(0.0, (), "")]
    for candidate in scored[:24]:
        next_states = list(states)
        for utility, selected, _ in states:
            if any(
                _key(other.fragment.address) == _key(candidate.fragment.address)
                and other.fragment.start < candidate.fragment.end
                and candidate.fragment.start < other.fragment.end
                for other in selected
            ):
                continue
            chosen = (*selected, candidate)
            fragments = _merge(chosen, originals)
            content = _render(fragments)
            if len(content.encode("utf-8")) > request.max_bytes:
                continue
            next_states.append((utility + candidate.score, chosen, content))
        distinct = {}
        for state in next_states:
            if state[2] not in distinct or state[0] > distinct[state[2]][0]:
                distinct[state[2]] = state
        states = sorted(distinct.values(), key=lambda state: (-state[0], len(state[2].encode("utf-8"))))[:48]
    _, selected, content = states[0]
    fragments = _merge(selected, originals)
    return PreparedContextBuild(
        context=PreparedContext(
            status="ready" if fragments else "empty",
            content=content or None,
            content_bytes=len(content.encode("utf-8")),
        ),
        origins=tuple(fragment.address for fragment in fragments),
        fragments=fragments,
    )


def _score_candidates(sentences, query, originals, entities):
    frequency = Counter(term for sentence in sentences for term in set(sentence.terms))
    average = sum(len(sentence.terms) for sentence in sentences) / max(1, len(sentences))
    scored = []
    by_entry = {}
    for sentence in sentences:
        by_entry.setdefault(_key(sentence.fragment.address), []).append(sentence)
    entity_weights = {
        term: 4.0
        for term in entities
        if sum(any(term in sentence.terms for sentence in entry) for entry in by_entry.values()) == 1
    }
    raw_scores = {}
    for sentence in sentences:
        counts = Counter(sentence.terms)
        score = sum(
            math.log(1 + (len(sentences) - frequency[term] + 0.5) / (frequency[term] + 0.5))
            * entity_weights.get(term, 1.0)
            * (counts[term] * 2.2)
            / (counts[term] + 1.2 * (0.25 + 0.75 * len(sentence.terms) / max(1, average)))
            for term in sorted(query & counts.keys())
        )
        raw_scores[id(sentence)] = score
    document_weights = _document_weights(by_entry, query, entity_weights)
    for entry_key, entry_sentences in by_entry.items():
        peak = max(raw_scores[id(sentence)] for sentence in entry_sentences)
        for index, sentence in enumerate(entry_sentences):
            score = _sentence_score(sentence, raw_scores[id(sentence)], peak, index / max(1, len(entry_sentences) - 1))
            score *= document_weights[entry_key]
            if not score:
                continue
            scored.append(_Sentence(sentence.fragment, sentence.terms, score))
            for neighbor_index in (index - 1, index + 1):
                if not 0 <= neighbor_index < len(entry_sentences):
                    continue
                neighbor = entry_sentences[neighbor_index]
                first, last = sorted((sentence.fragment, neighbor.fragment), key=lambda fragment: fragment.start)
                original = originals[_key(first.address)]
                fragment = PreparedEvidenceFragment(
                    first.address, first.start, last.end, original[first.start : last.end]
                )
                scored.append(
                    _Sentence(
                        fragment,
                        (*sentence.terms, *neighbor.terms),
                        score * 1.2 + raw_scores[id(neighbor)] * document_weights[entry_key] * 0.4,
                    )
                )
    return _unique_candidates(scored)


def _sentence_score(sentence, score, peak, position):
    # Numerical results may answer a claim without repeating the paper's entities.
    if re.match(r"\s*(?:RESULTS?|CONCLUSIONS?)\b", sentence.fragment.text):
        score += peak * 0.35
    score *= 1 + 0.35 * position
    if re.search(
        r"\b(results?|conclusions?|demonstrate[ds]?|observed|we show|we found)\b", sentence.fragment.text, re.I
    ):
        score *= 1.5
    return score


def _document_weights(by_entry, query, entity_weights):
    """Keep isolated generic matches from displacing coherent document evidence."""
    terms = {key: {term for sentence in sentences for term in sentence.terms} for key, sentences in by_entry.items()}
    frequency = Counter(term for vocabulary in terms.values() for term in vocabulary)
    weights = {
        term: (1 + math.log((len(terms) + 1) / (frequency[term] + 0.5))) * entity_weights.get(term, 1.0)
        for term in query
        if frequency[term]
    }
    coverage = {
        key: sum(weights[term] for term in sorted(weights.keys() & vocabulary)) for key, vocabulary in terms.items()
    }
    best = max(coverage.values(), default=0) or 1
    return {key: 0.25 + 0.75 * (score / best) ** 2 for key, score in coverage.items()}


def _unique_candidates(scored):
    """A neighboring pair can be proposed from either sentence; count it once."""
    distinct = {}
    for sentence in scored:
        key = (_key(sentence.fragment.address), sentence.fragment.start, sentence.fragment.end)
        if key not in distinct or sentence.score > distinct[key].score:
            distinct[key] = sentence
    return sorted(distinct.values(), key=lambda sentence: (-sentence.score, sentence.fragment.text))
