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
])
_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")


def _terms(text):
    terms = []
    for term in _WORDS.findall(text.casefold()):
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
            end = len(hit.text) if boundary is None else boundary.start()
            left, right = start, end
            while left < right and hit.text[left].isspace():
                left += 1
            while right > left and hit.text[right - 1].isspace():
                right -= 1
            text = hit.text[left:right]
            if text and text not in seen:
                seen.add(text)
                yield _Sentence(PreparedEvidenceFragment(address, left, right, text), tuple(_terms(text)))
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
        groups.setdefault(_key(fragment.address), []).append(fragment)
    merged = []
    for key, spans in groups.items():
        address = spans[0].address
        text = originals[key]
        current = None
        for span in sorted(spans, key=lambda item: item.start):
            if current is not None and (span.start <= current.end or not text[current.end : span.start].strip()):
                end = max(current.end, span.end)
                current = PreparedEvidenceFragment(address, current.start, end, text[current.start : end])
            else:
                if current is not None:
                    merged.append(current)
                current = span
        if current is not None:
            merged.append(current)
    return tuple(merged)


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
    originals = {
        _key(
            MemoryEntryAddress(
                ArtifactAddress(scope_id=group.scope_id, artifact=hit.memory_ref), hit.entry_id, hit.entry_version_id
            )
        ): hit.text
        for group in groups
        for hit in group.hits
    }
    scored = _score_candidates(sentences, query, originals)
    # A small bounded beam trades citation overhead against evidence coverage. All
    # states contain literal spans; every candidate is measured after serialization.
    states = [(0.0, (), frozenset(), "")]
    for candidate in scored[:24]:
        next_states = list(states)
        for utility, selected, covered, _ in states:
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
            new_terms = frozenset(candidate.terms) & query
            gain = candidate.score * (0.3 + 0.7 * len(new_terms - covered) / max(1, len(new_terms)))
            next_states.append((utility + gain, chosen, covered | new_terms, content))
        states = sorted(next_states, key=lambda state: (-state[0], len(state[3].encode("utf-8"))))[:48]
    _, selected, _, content = states[0]
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


def _score_candidates(sentences, query, originals):
    frequency = Counter(term for sentence in sentences for term in set(sentence.terms))
    average = sum(len(sentence.terms) for sentence in sentences) / max(1, len(sentences))
    scored = []
    raw_scores = {}
    for sentence in sentences:
        counts = Counter(sentence.terms)
        score = sum(
            math.log(1 + (len(sentences) - frequency[term] + 0.5) / (frequency[term] + 0.5))
            * (counts[term] * 2.2)
            / (counts[term] + 1.2 * (0.25 + 0.75 * len(sentence.terms) / max(1, average)))
            for term in query & counts.keys()
        )
        raw_scores[id(sentence)] = score
    by_entry = {}
    for sentence in sentences:
        by_entry.setdefault(_key(sentence.fragment.address), []).append(sentence)
    for entry_sentences in by_entry.values():
        for index, sentence in enumerate(entry_sentences):
            score = raw_scores[id(sentence)]
            if not score:
                continue
            # Abstract conclusions and explicit observations are modest priors,
            # not evidence substitutes; all selections remain original spans.
            position = index / max(1, len(entry_sentences) - 1)
            score *= 1 + 0.2 * position
            if re.search(
                r"\b(results?|conclusions?|demonstrate[ds]?|observed|we show|we found)\b", sentence.fragment.text, re.I
            ):
                score *= 1.15
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
                        fragment, (*sentence.terms, *neighbor.terms), score * 1.2 + raw_scores[id(neighbor)] * 0.4
                    )
                )
    scored.sort(key=lambda sentence: -sentence.score)
    return scored
