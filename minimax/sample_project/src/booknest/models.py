"""Domain models for the BookNest library catalog.

The catalog is intentionally small and dependency-free so that the sample can
run on a clean machine with nothing but the Python standard library.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Book:
    """One borrowable title in the library."""

    id: int
    title: str
    author: str
    topic: str
    published_year: int
    copies_total: int
    copies_available: int


@dataclass(frozen=True)
class BookPage:
    """One page of a catalog listing plus the size of the filtered result set."""

    items: tuple[Book, ...]
    page: int
    page_size: int
    total: int
