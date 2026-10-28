"""回归测试：HTTP 适配器的既有错误码与默认行为（``API-002`` / ``API-004``）。"""

from __future__ import annotations

import pytest

from booknest.api import list_books_response
from booknest.catalog import CatalogService
from booknest.store import seed_books


def _service() -> CatalogService:
    return CatalogService(seed_books())


def test_empty_query_returns_first_page() -> None:
    """覆盖 API-004：不传参数时保持默认分页。"""

    status, payload = list_books_response(_service(), {})

    assert status == 200
    assert payload["page"] == 1
    assert payload["page_size"] == 20
    assert payload["total"] == 12
    assert len(payload["items"]) == 12


@pytest.mark.parametrize("query", [{"page": "0"}, {"page": "abc"}, {"page_size": "51"}, {"page_size": "x"}])
def test_invalid_paging_returns_400(query: dict[str, str]) -> None:
    """覆盖 API-002：非法分页参数返回 400 与 error 字段。"""

    status, payload = list_books_response(_service(), query)

    assert status == 400
    assert set(payload) == {"error"}
    assert payload["error"]


def test_invalid_available_only_returns_400() -> None:
    """覆盖 API-002：非法布尔值返回 400。"""

    status, payload = list_books_response(_service(), {"available_only": "sometimes"})

    assert status == 400
    assert payload["error"]


@pytest.mark.parametrize("raw", ["1", "true", "YES", "on"])
def test_boolean_spellings_are_accepted(raw: str) -> None:
    """覆盖 API-004：布尔参数的既有写法保持兼容。"""

    status, _payload = list_books_response(_service(), {"available_only": raw})

    assert status == 200
