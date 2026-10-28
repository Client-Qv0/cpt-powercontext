"""回归测试：分页契约必须保持原样（对应 ``BOOK-002``）。"""

from __future__ import annotations

import pytest

from booknest.catalog import MAX_PAGE_SIZE, CatalogService
from booknest.store import seed_books


def _service() -> CatalogService:
    return CatalogService(seed_books())


def test_default_page_size_is_twenty() -> None:
    """覆盖 BOOK-002：page_size 默认值为 20。"""

    page = _service().list_books()

    assert page.page_size == 20
    assert page.page == 1


def test_second_page_starts_after_the_first_page() -> None:
    """覆盖 BOOK-002：页码从 1 开始，切页偏移为 (page-1)*page_size。"""

    first = _service().list_books(page=1, page_size=5)
    second = _service().list_books(page=2, page_size=5)

    assert [book.id for book in first.items] == [2, 3, 1, 10, 5]
    assert [book.id for book in second.items] == [6, 12, 9, 4, 11]
    assert first.total == second.total == 12


def test_page_beyond_the_end_returns_empty_items() -> None:
    """覆盖 BOOK-002：越界页码返回空 items，但 total 保持筛选后总数。"""

    page = _service().list_books(page=99, page_size=5)

    assert page.items == ()
    assert page.total == 12


def test_maximum_page_size_is_allowed() -> None:
    """覆盖 BOOK-002：page_size 允许取到 50。"""

    page = _service().list_books(page_size=MAX_PAGE_SIZE)

    assert page.page_size == MAX_PAGE_SIZE
    assert len(page.items) == 12


@pytest.mark.parametrize("page", [0, -1])
def test_invalid_page_raises_value_error(page: int) -> None:
    """覆盖 BOOK-002：page 小于 1 时抛出 ValueError。"""

    with pytest.raises(ValueError):
        _service().list_books(page=page)


@pytest.mark.parametrize("page_size", [0, -1, 51])
def test_invalid_page_size_raises_value_error(page_size: int) -> None:
    """覆盖 BOOK-002：page_size 超出 1..50 时抛出 ValueError。"""

    with pytest.raises(ValueError):
        _service().list_books(page_size=page_size)
