## 任务
- id: `TASK-BOOK-0042`
- 标题: 书目列表支持主题与在架筛选

GET /books（CatalogService.list_books）需要支持按主题 topic 和在架状态 available_only 筛选。topic 精确匹配、大小写不敏感，空字符串视为不筛选；available_only 为 true 时只返回有可借复本的书；两者同时出现时取交集。筛选必须先于排序和分页执行，total 要反映筛选后的数量。未知主题返回空列表，不能报错。不能改变默认排序、分页校验、响应结构以及已有调用方的行为。

## 必须保持的既有行为
- 不传筛选参数时，默认按 title 升序、相同 title 按 id 升序排序
- page_size 默认 20，取值范围 1..50，非法值仍返回 400
- 响应结构 items/page/page_size/total 与 Book 字段保持不变
- 未知 topic 返回 200 与空列表，total 为 0

## 有效规格（来自 seekdb 索引，均来自仓库真实文件）

### [BOOK-004] [BOOK-004] 主题与在架筛选 (specs/catalog.md:35-47, revision 1)
## [BOOK-004] 主题与在架筛选

本条目是 v3 新增需求，对应任务 `TASK-BOOK-0042`：

- `topic`：主题 slug 的精确匹配，比较时先去除首尾空白并忽略大小写。
  空字符串或未提供等同于不筛选。未知主题返回空结果，而不是错误。
- `available_only`：为 `true` 时仅保留 `copies_available > 0` 的书；
  为 `false` 或缺省时不做在架过滤。
- 两个筛选参数同时出现时，结果取交集（AND 语义）。
- 筛选必须先于排序和分页执行，`total` 必须反映筛选后的总数。
- 新筛选不得改变 `BOOK-001` 的排序、`BOOK-002` 的分页校验与
  `BOOK-003` 的响应结构。

### [API-001] [API-001] GET /books 查询参数 (specs/api.md:13-24, revision 1)
## [API-001] GET /books 查询参数

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `page` | integer | 1 | 页码，必须大于等于 1 |
| `page_size` | integer | 20 | 每页条数，1 到 50 |
| `topic` | string | 无 | 主题 slug，大小写不敏感，空串视为未提供 |
| `available_only` | boolean | false | 仅返回可借复本大于 0 的书 |

布尔参数接受 `1/0`、`true/false`、`yes/no`、`on/off`（忽略大小写）。
其余取值返回 400。

### [BOOK-005] [BOOK-005] 边界与错误 (specs/catalog.md:48-52, revision 1)
## [BOOK-005] 边界与错误

- 未知 `topic`：返回 200 与空 `items`，`total` 为 0，不抛出错误。
- 非法 `page` / `page_size` / `available_only`：沿用 `API-002` 的 400 响应。
- 目录为空、页码越界：返回 200 与空 `items`，`total` 为 0 或筛选后总数。

### [ADR-0008] [ADR-0008] 筛选先于分页，主题使用 slug (specs/decisions/ADR-0008.md:10-19, revision 1)
## [ADR-0008] 筛选先于分页，主题使用 slug

- **状态**：accepted（2026-10-20），取代 ADR-0003 中"先分页后过滤"的临时方案。
- **背景**：v3 需要在 `GET /books` 上增加 `topic` 与 `available_only` 两个筛选。
  如果先切页再过滤，`total`、页码和空页都会给出错误结果，调用方无法翻页。
- **决定**：筛选一律在排序与分页之前完成。`topic` 使用小写 slug 精确匹配，
  比较时使用 `casefold()`；`available_only` 直接比较 `copies_available > 0`。
  未知主题返回空结果，不引入新的错误码。
- **影响**：`total` 变成筛选后的总数；默认排序 `BOOK-001` 与分页校验 `BOOK-002`
  保持不变；实现不得在 API 层做过滤，以免两处语义漂移。

### [BOOK-001] [BOOK-001] 默认排序 (specs/catalog.md:14-19, revision 1)
## [BOOK-001] 默认排序

列表必须按 `title` 升序排列；当 `title` 完全相同时，按 `id` 升序排列。
排序必须稳定，且不受筛选参数影响。调用方不传任何筛选参数时，返回顺序必须与
本规格引入前完全一致。

### [BOOK-002] [BOOK-002] 分页契约 (specs/catalog.md:20-28, revision 1)
## [BOOK-002] 分页契约

- `page` 从 1 开始计数，默认值为 1。
- `page_size` 默认值为 20，允许的取值范围是 1 到 50（含边界）。
- `page` 小于 1、`page_size` 小于 1 或大于 50 时，服务层抛出 `ValueError`，
  HTTP 层返回 400。
- 分页必须作用在筛选后的结果集上：先筛选、再排序、最后切页。
- `total` 表示当前筛选条件下全部结果的数量，而不是当前页的条数。

### [BOOK-003] [BOOK-003] 列表响应结构 (specs/catalog.md:29-34, revision 1)
## [BOOK-003] 列表响应结构

列表结果由 `items`、`page`、`page_size`、`total` 四个字段组成。`items` 中每个元素
保留 `id`、`title`、`author`、`topic`、`published_year`、`copies_total`、
`copies_available` 七个字段。字段名、类型与嵌套结构不得改变。

### [API-004] [API-004] 兼容性 (specs/api.md:36-39, revision 1)
## [API-004] 兼容性

已存在的调用方只使用 `page` 与 `page_size`。新增参数不得改变既有请求的
响应结构、默认分页大小、错误码和排序顺序。

### [API-002] [API-002] 错误响应 (specs/api.md:25-30, revision 1)
## [API-002] 错误响应

参数校验失败时返回状态码 400，响应体为 `{"error": "<reason>"}`。
未知 `topic` 不是错误，必须返回 200 与空列表；服务端不得因为筛选没有命中
而返回 404。

## 待修改代码（完整文件）

### `src/booknest/catalog.py`
```python
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

        ordered = sorted(self._books, key=lambda book: (book.title, book.id))
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
```
相关符号: CatalogService.list_books, CatalogService, booknest.catalog, CatalogService._validate_paging, CatalogService.__init__

### `src/booknest/api.py`
```python
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
```
相关符号: list_books_response, _page_payload, _parse_bool

## 目标功能测试（修改前失败，修改后必须全部通过；禁止修改这些文件）

### `tests/test_catalog_filters.py::test_api_available_only_is_forwarded`
```python
def test_api_available_only_is_forwarded(service: CatalogService) -> None:
    """覆盖 API-001：HTTP 适配器把 available_only 传入服务层。"""

    status, payload = list_books_response(service, {"available_only": "1"})

    assert status == 200
    assert payload["total"] == 9
    assert all(item["copies_available"] > 0 for item in payload["items"])
```

### `tests/test_catalog_filters.py::test_api_topic_and_available_pagination`
```python
def test_api_topic_and_available_pagination(service: CatalogService) -> None:
    """覆盖 API-001/API-003：HTTP 层的筛选、分页与 total 保持一致。"""

    status, payload = list_books_response(
        service, {"topic": "database", "available_only": "true", "page": "2", "page_size": "1"}
    )

    assert status == 200
    assert payload["total"] == 2
    assert payload["page"] == 2
    assert [item["id"] for item in payload["items"]] == [12]
```

### `tests/test_catalog_filters.py::test_available_only_excludes_checked_out_books`
```python
def test_available_only_excludes_checked_out_books(service: CatalogService) -> None:
    """覆盖 BOOK-004：available_only 仅保留可借复本大于 0 的书。"""

    page = service.list_books(available_only=True, page_size=50)

    assert page.total == 9
    assert all(book.copies_available > 0 for book in page.items)
    assert {book.id for book in page.items}.isdisjoint({2, 6, 9})
```

### `tests/test_catalog_filters.py::test_filters_apply_before_pagination`
```python
def test_filters_apply_before_pagination(service: CatalogService) -> None:
    """覆盖 BOOK-002/BOOK-004：先筛选再分页，total 是筛选后的总数。"""

    first = service.list_books(topic="database", page=1, page_size=2)
    second = service.list_books(topic="database", page=2, page_size=2)

    assert first.total == 3
    assert [book.id for book in first.items] == [2, 1]
    assert second.total == 3
    assert [book.id for book in second.items] == [12]
```

### `tests/test_catalog_filters.py::test_topic_and_available_filters_combine_with_and`
```python
def test_topic_and_available_filters_combine_with_and(service: CatalogService) -> None:
    """覆盖 BOOK-004 与 ADR-0008：两个筛选参数按 AND 组合。"""

    page = service.list_books(topic="database", available_only=True, page_size=50)

    assert page.total == 2
    assert [book.id for book in page.items] == [1, 12]
```

### `tests/test_catalog_filters.py::test_topic_filter_is_case_insensitive`
```python
def test_topic_filter_is_case_insensitive(service: CatalogService) -> None:
    """覆盖 BOOK-004：topic 比较忽略大小写与首尾空白。"""

    page = service.list_books(topic="  DATABASE  ", page_size=50)

    assert page.total == 3
    assert {book.topic for book in page.items} == {"database"}
```

### `tests/test_catalog_filters.py::test_topic_filter_returns_only_matching_topic`
```python
def test_topic_filter_returns_only_matching_topic(service: CatalogService) -> None:
    """覆盖 BOOK-004：topic 精确匹配只返回该主题。"""

    page = service.list_books(topic="database", page_size=50)

    assert page.total == 3
    assert [book.id for book in page.items] == [2, 1, 12]
    assert {book.topic for book in page.items} == {"database"}
```

### `tests/test_catalog_filters.py::test_unknown_topic_returns_empty_page`
```python
def test_unknown_topic_returns_empty_page(service: CatalogService) -> None:
    """覆盖 BOOK-005：未知主题返回空结果而不是错误。"""

    page = service.list_books(topic="astronomy", page_size=50)

    assert page.items == ()
    assert page.total == 0
```

## 回归测试（修改前后都必须通过；禁止修改这些文件）
- `tests/test_api_contract.py::test_boolean_spellings_are_accepted`
- `tests/test_api_contract.py::test_empty_query_returns_first_page`
- `tests/test_api_contract.py::test_invalid_available_only_returns_400`
- `tests/test_api_contract.py::test_invalid_paging_returns_400`
- `tests/test_catalog_contract.py::test_api_payload_shape_is_unchanged`
- `tests/test_catalog_contract.py::test_default_listing_keeps_title_then_id_order`
- `tests/test_catalog_contract.py::test_default_listing_returns_every_seed_book`
- `tests/test_catalog_contract.py::test_page_shape_is_unchanged`
- `tests/test_pagination.py::test_default_page_size_is_twenty`
- `tests/test_pagination.py::test_invalid_page_raises_value_error`
- `tests/test_pagination.py::test_invalid_page_size_raises_value_error`
- `tests/test_pagination.py::test_maximum_page_size_is_allowed`
- `tests/test_pagination.py::test_page_beyond_the_end_returns_empty_items`
- `tests/test_pagination.py::test_second_page_starts_after_the_first_page`

## 输出格式
只输出一个 unified diff，例如：
--- a/src/booknest/catalog.py
+++ b/src/booknest/catalog.py
@@ -10,6 +10,9 @@
 ...
不要输出围栏以外的说明文字。