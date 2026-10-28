"""回归测试：目录排序与响应结构必须保持原样。

这些测试在代码修改前后都必须通过（对应 ``BOOK-001`` / ``BOOK-003``）。
"""

from __future__ import annotations

from booknest.api import list_books_response
from booknest.catalog import CatalogService
from booknest.store import seed_books


def _service() -> CatalogService:
    return CatalogService(seed_books())


def test_default_listing_keeps_title_then_id_order() -> None:
    """覆盖 BOOK-001：默认排序为 title 升序，其次 id 升序。"""

    page = _service().list_books(page_size=50)
    expected = sorted(seed_books(), key=lambda book: (book.title, book.id))

    assert [book.id for book in page.items] == [book.id for book in expected]
    assert page.total == 12


def test_default_listing_returns_every_seed_book() -> None:
    """覆盖 BOOK-001：不传筛选参数时返回全部馆藏。"""

    page = _service().list_books()

    assert page.total == 12
    assert len(page.items) == 12


def test_page_shape_is_unchanged() -> None:
    """覆盖 BOOK-003：BookPage 的字段与类型保持稳定。"""

    page = _service().list_books()

    assert page.page == 1
    assert page.page_size == 20
    assert isinstance(page.items, tuple)
    assert all(item.__class__.__name__ == "Book" for item in page.items)


def test_api_payload_shape_is_unchanged() -> None:
    """覆盖 API-003：HTTP 适配器响应字段保持稳定。"""

    status, payload = list_books_response(_service(), {})

    assert status == 200
    assert set(payload) == {"items", "page", "page_size", "total"}
    assert set(payload["items"][0]) == {
        "id",
        "title",
        "author",
        "topic",
        "published_year",
        "copies_total",
        "copies_available",
    }
