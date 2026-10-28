"""Small reporting helpers (kept in the sample to make retrieval discriminate)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from .models import Book


def monthly_summary(books: Iterable[Book]) -> dict[str, object]:
    """Return the topic distribution used by the monthly operations report."""

    materialised = tuple(books)
    topics = Counter(book.topic for book in materialised)
    return {
        "titles": len(materialised),
        "topics": dict(sorted(topics.items())),
        "available_titles": sum(1 for book in materialised if book.copies_available > 0),
    }
