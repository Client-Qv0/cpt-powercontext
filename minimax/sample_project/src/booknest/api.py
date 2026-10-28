"""A tiny HTTP-agnostic adapter for the public ``GET /books`` endpoint.

The adapter mirrors what the real HTTP layer does: parse query strings,
translate validation errors into status codes, and serialise the page.  It is
kept framework-free so the sample can be tested without a web server.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .catalog import CatalogService
from .models import BookPage

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def list_books_response(
    service: CatalogService, query: Mapping[str, str]
) -> tuple[int, dict[str, Any]]:
    """Return ``(status_code, payload)`` for one ``GET /books`` request."""

    try:
        page = _parse_int(query.get("page"), default=1)
        page_size = _parse_int(query.get("page_size"), default=20)
        available_only = _parse_bool(query.get("available_only"))
        result = service.list_books(
            page=page,
            page_size=page_size,
            topic=query.get("topic"),
            available_only=available_only,
        )
    except ValueError as exc:
        return 400, {"error": str(exc)}
    return 200, _page_payload(result)


def _parse_int(raw: str | None, *, default: int) -> int:
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid integer: {raw!r}") from exc


def _parse_bool(raw: str | None) -> bool:
    if raw is None or raw == "":
        return False
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"invalid boolean: {raw!r}")


def _page_payload(result: BookPage) -> dict[str, Any]:
    return {
        "items": [
            {
                "id": book.id,
                "title": book.title,
                "author": book.author,
                "topic": book.topic,
                "published_year": book.published_year,
                "copies_total": book.copies_total,
                "copies_available": book.copies_available,
            }
            for book in result.items
        ],
        "page": result.page,
        "page_size": result.page_size,
        "total": result.total,
    }
