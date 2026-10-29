"""Catalog listing service.

The service owns ordering, pagination and (as of the current task) the
optional filtering of the public ``GET /books`` listing.
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import Book, BookPage

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50


class CatalogService:
    """Read-only view over the library's books."""

    def __init__(self, books: Iterable[Book]) -> None:
        self._books: tuple[Book, ...] = tuple(books)

    def list_books(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        topic: str | None = None,
        available_only: bool = False,
    ) -> BookPage:
        """Return one page of the catalog.

        ``topic`` and ``available_only`` are accepted by the public listing
        contract and are expected to narrow the result set.  Ordering stays
        stable: title ascending, then id ascending.
        """

        self._validate_paging(page, page_size)

        filtered = self._books
        if topic is not None:
            normalized_topic = topic.strip().casefold()
            if normalized_topic:
                filtered = tuple(
                    book
                    for book in filtered
                    if book.topic.strip().casefold() == normalized_topic
                )

        if available_only:
            filtered = tuple(
                book for book in filtered if book.copies_available > 0
            )

        ordered = sorted(filtered, key=lambda book: (book.title, book.id))
        start = (page - 1) * page_size
        return BookPage(
            items=tuple(ordered[start : start + page_size]),
            page=page,
            page_size=page_size,
            total=len(ordered),
        )

    @staticmethod
    def _validate_paging(page: int, page_size: int) -> None:
        if page < 1:
            raise ValueError("page must be greater than or equal to 1")
        if page_size < 1 or page_size > MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
