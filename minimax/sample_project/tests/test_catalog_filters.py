"""目标功能测试：v3 的主题与在架筛选。

这些测试在本次代码修改前失败，修改后必须全部通过。它们由任务
``TASK-BOOK-0042`` 与规格 ``BOOK-004`` / ``API-001`` 共同定义。
"""

from __future__ import annotations

import pytest

from booknest.api import list_books_response
from booknest.catalog import CatalogService
from booknest.store import seed_books


@pytest.fixture()
def service() -> CatalogService:
    return CatalogService(seed_books())


def test_topic_filter_returns_only_matching_topic(service: CatalogService) -> None:
    """覆盖 BOOK-004：topic 精确匹配只返回该主题。"""

    page = service.list_books(topic="database", page_size=50)

    assert page.total == 3
    assert [book.id for book in page.items] == [2, 1, 12]
    assert {book.topic for book in page.items} == {"database"}


def test_topic_filter_is_case_insensitive(service: CatalogService) -> None:
    """覆盖 BOOK-004：topic 比较忽略大小写与首尾空白。"""

    page = service.list_books(topic="  DATABASE  ", page_size=50)

    assert page.total == 3
    assert {book.topic for book in page.items} == {"database"}


def test_available_only_excludes_checked_out_books(service: CatalogService) -> None:
    """覆盖 BOOK-004：available_only 仅保留可借复本大于 0 的书。"""

    page = service.list_books(available_only=True, page_size=50)

    assert page.total == 9
    assert all(book.copies_available > 0 for book in page.items)
    assert {book.id for book in page.items}.isdisjoint({2, 6, 9})


def test_topic_and_available_filters_combine_with_and(service: CatalogService) -> None:
    """覆盖 BOOK-004 与 ADR-0008：两个筛选参数按 AND 组合。"""

    page = service.list_books(topic="database", available_only=True, page_size=50)

    assert page.total == 2
    assert [book.id for book in page.items] == [1, 12]


def test_filters_apply_before_pagination(service: CatalogService) -> None:
    """覆盖 BOOK-002/BOOK-004：先筛选再分页，total 是筛选后的总数。"""

    first = service.list_books(topic="database", page=1, page_size=2)
    second = service.list_books(topic="database", page=2, page_size=2)

    assert first.total == 3
    assert [book.id for book in first.items] == [2, 1]
    assert second.total == 3
    assert [book.id for book in second.items] == [12]


def test_unknown_topic_returns_empty_page(service: CatalogService) -> None:
    """覆盖 BOOK-005：未知主题返回空结果而不是错误。"""

    page = service.list_books(topic="astronomy", page_size=50)

    assert page.items == ()
    assert page.total == 0


def test_api_available_only_is_forwarded(service: CatalogService) -> None:
    """覆盖 API-001：HTTP 适配器把 available_only 传入服务层。"""

    status, payload = list_books_response(service, {"available_only": "1"})

    assert status == 200
    assert payload["total"] == 9
    assert all(item["copies_available"] > 0 for item in payload["items"])


def test_api_topic_and_available_pagination(service: CatalogService) -> None:
    """覆盖 API-001/API-003：HTTP 层的筛选、分页与 total 保持一致。"""

    status, payload = list_books_response(
        service, {"topic": "database", "available_only": "true", "page": "2", "page_size": "1"}
    )

    assert status == 200
    assert payload["total"] == 2
    assert payload["page"] == 2
    assert [item["id"] for item in payload["items"]] == [12]
