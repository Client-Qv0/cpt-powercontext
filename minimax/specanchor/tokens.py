"""Deterministic tokenisation used by both import and retrieval.

The sample is bilingual (Chinese specifications, English identifiers), so the
tokenizer emits ASCII word/identifier pieces and Chinese character bigrams.
Using the same function for indexing and querying keeps scoring honest and
avoids a heavyweight NLP dependency.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]*")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "will",
        "with",
        "must",
        "should",
        "can",
        "not",
        "no",
        "if",
        "then",
        "than",
        "when",
        "where",
        "which",
        "who",
        "how",
        "what",
        "all",
        "any",
        "only",
        "into",
        "over",
        "under",
        "per",
        "via",
    }
)


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def tokenize(text: str) -> list[str]:
    """Return weighted-agnostic terms for one piece of text."""

    if not text:
        return []
    normalized = normalize(text)
    tokens: list[str] = []

    for run in _CJK_RUN.findall(normalized):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))

    for raw in _WORD.findall(text):
        for part in _split_identifier(raw):
            part = part.lower()
            if len(part) < 2 or part in _STOPWORDS:
                continue
            if part.isdigit():
                continue
            tokens.append(part)
    return tokens


def _split_identifier(raw: str) -> list[str]:
    parts: list[str] = []
    for camel in _CAMEL.split(raw):
        parts.extend(piece for piece in re.split(r"[._\-]+", camel) if piece)
    # Keep the joined spelling as well: ``available_only`` is a real parameter
    # name that a task description may quote verbatim.
    joined = "".join(parts).lower()
    if joined and joined not in parts:
        parts.append(joined)
    return parts


def term_frequencies(tokens: list[str]) -> Counter[str]:
    return Counter(token for token in tokens if token)


def token_count(tokens: list[str]) -> int:
    return sum(term_frequencies(tokens).values())
