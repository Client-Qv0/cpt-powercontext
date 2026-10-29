# MiniMax 开发记录 · TASK-BOOK-0042

- 生成时间：2026-10-29T08:07:51+08:00
- 代码版本：`b185a1c33fb36d39f7437d8da6254c7eb0e5af62`
- 运行目录：`evidence/runs/20261029-080429-TASK-BOOK-0042-run-ca941f5461`
- 任务：书目列表支持主题与在架筛选

## 1. 交给 MiniMax 的任务上下文

上下文由 `specanchor context` 从 seekdb 索引中选出，未人工拼装：

| 类型 | 来源 | 说明 |
| --- | --- | --- |
| 规格 | `specs/catalog.md:35-47` | `BOOK-004` [BOOK-004] 主题与在架筛选 (rev 1) |
| 规格 | `specs/api.md:13-24` | `API-001` [API-001] GET /books 查询参数 (rev 1) |
| 规格 | `specs/catalog.md:48-52` | `BOOK-005` [BOOK-005] 边界与错误 (rev 1) |
| 规格 | `specs/decisions/ADR-0008.md:10-19` | `ADR-0008` [ADR-0008] 筛选先于分页，主题使用 slug (rev 1) |
| 规格 | `specs/catalog.md:14-19` | `BOOK-001` [BOOK-001] 默认排序 (rev 1) |
| 规格 | `specs/catalog.md:20-28` | `BOOK-002` [BOOK-002] 分页契约 (rev 1) |
| 规格 | `specs/catalog.md:29-34` | `BOOK-003` [BOOK-003] 列表响应结构 (rev 1) |
| 规格 | `specs/api.md:36-39` | `API-004` [API-004] 兼容性 (rev 1) |
| 规格 | `specs/api.md:25-30` | `API-002` [API-002] 错误响应 (rev 1) |
| 代码 | `src/booknest/catalog.py:23-47` | `CatalogService.list_books` |
| 代码 | `src/booknest/api.py:20-37` | `list_books_response` |
| 代码 | `src/booknest/api.py:60-77` | `_page_payload` |
| 代码 | `src/booknest/catalog.py:17-54` | `CatalogService` |
| 代码 | `src/booknest/catalog.py:1-54` | `booknest.catalog` |
| 代码 | `src/booknest/api.py:49-57` | `_parse_bool` |
| 代码 | `src/booknest/catalog.py:50-54` | `CatalogService._validate_paging` |
| 代码 | `src/booknest/catalog.py:20-21` | `CatalogService.__init__` |
| 目标测试 | `tests/test_catalog_filters.py::test_api_available_only_is_forwarded` | 覆盖目标规格 API-001 |
| 目标测试 | `tests/test_catalog_filters.py::test_api_topic_and_available_pagination` | 覆盖目标规格 API-001 |
| 目标测试 | `tests/test_catalog_filters.py::test_available_only_excludes_checked_out_books` | 覆盖目标规格 BOOK-004 |
| 目标测试 | `tests/test_catalog_filters.py::test_filters_apply_before_pagination` | 覆盖目标规格 BOOK-004 |
| 目标测试 | `tests/test_catalog_filters.py::test_topic_and_available_filters_combine_with_and` | 覆盖目标规格 BOOK-004 |
| 目标测试 | `tests/test_catalog_filters.py::test_topic_filter_is_case_insensitive` | 覆盖目标规格 BOOK-004 |
| 目标测试 | `tests/test_catalog_filters.py::test_topic_filter_returns_only_matching_topic` | 覆盖目标规格 BOOK-004 |
| 目标测试 | `tests/test_catalog_filters.py::test_unknown_topic_returns_empty_page` | 覆盖目标规格 BOOK-005 |
| 回归测试 | `tests/test_api_contract.py::test_boolean_spellings_are_accepted` | 导入受影响模块 booknest.api, booknest.catalog |
| 回归测试 | `tests/test_api_contract.py::test_empty_query_returns_first_page` | 导入受影响模块 booknest.api, booknest.catalog |
| 回归测试 | `tests/test_api_contract.py::test_invalid_available_only_returns_400` | 导入受影响模块 booknest.api, booknest.catalog |
| 回归测试 | `tests/test_api_contract.py::test_invalid_paging_returns_400` | 导入受影响模块 booknest.api, booknest.catalog |
| 回归测试 | `tests/test_catalog_contract.py::test_api_payload_shape_is_unchanged` | 导入受影响模块 booknest.api, booknest.catalog |
| 回归测试 | `tests/test_catalog_contract.py::test_default_listing_keeps_title_then_id_order` | 导入受影响模块 booknest.api, booknest.catalog |
| 回归测试 | `tests/test_catalog_contract.py::test_default_listing_returns_every_seed_book` | 导入受影响模块 booknest.api, booknest.catalog |
| 回归测试 | `tests/test_catalog_contract.py::test_page_shape_is_unchanged` | 导入受影响模块 booknest.api, booknest.catalog |
| 回归测试 | `tests/test_pagination.py::test_default_page_size_is_twenty` | 导入受影响模块 booknest.catalog |
| 回归测试 | `tests/test_pagination.py::test_invalid_page_raises_value_error` | 导入受影响模块 booknest.catalog |
| 回归测试 | `tests/test_pagination.py::test_invalid_page_size_raises_value_error` | 导入受影响模块 booknest.catalog |
| 回归测试 | `tests/test_pagination.py::test_maximum_page_size_is_allowed` | 导入受影响模块 booknest.catalog |
| 回归测试 | `tests/test_pagination.py::test_page_beyond_the_end_returns_empty_items` | 导入受影响模块 booknest.catalog |
| 回归测试 | `tests/test_pagination.py::test_second_page_starts_after_the_first_page` | 导入受影响模块 booknest.catalog |

上下文摘要：`73dee0c3fb1099a98656a765bb52e1b94fd46e1d3e3505ce3f3bb13a5cc382fb`；构建时执行 10 条 seekdb 查询。

## 2. MiniMax 调用记录

- 接入方式：HTTP `POST {MINIMAX_BASE_URL}/chat/completions`（OpenAI 兼容）
- 模型：`MiniMax-M3.1-Flash`
- 尝试次数：1
- 第 1 次：3547 ms，usage={"total_tokens": 4551, "total_characters": 0, "prompt_tokens": 4098, "completion_tokens": 453, "completion_tokens_details": {"reasoning_tokens": 235}, "prompt_tokens_details": {"cached_tokens": 128}}，finish_reason=`stop`

> 请求中的 API Key 不写盘；这里只记录模型、时延、用量与补丁。

## 3. 代码修改

- 补丁文件：`evidence/patches/TASK-BOOK-0042.patch`
- 补丁 SHA-256：`220461fed8a9455c719645eebda1e4dbae82b40103a5b8cfb6d0ea0851a634f1`

```diff
--- a/src/booknest/catalog.py
+++ b/src/booknest/catalog.py
@@ -38,7 +38,22 @@ class CatalogService:
 
         self._validate_paging(page, page_size)
 
-        ordered = sorted(self._books, key=lambda book: (book.title, book.id))
+        filtered = self._books
+        if topic is not None:
+            normalized_topic = topic.strip().casefold()
+            if normalized_topic:
+                filtered = tuple(
+                    book
+                    for book in filtered
+                    if book.topic.strip().casefold() == normalized_topic
+                )
+
+        if available_only:
+            filtered = tuple(
+                book for book in filtered if book.copies_available > 0
+            )
+
+        ordered = sorted(filtered, key=lambda book: (book.title, book.id))
         start = (page - 1) * page_size
         return BookPage(
             items=tuple(ordered[start : start + page_size]),
```

## 4. 修改前 / 修改后测试

| 阶段 | 命令 | 退出码 | passed | failed | 日志 |
| --- | --- | ---: | ---: | ---: | --- |
| 修改前目标测试（预期失败） | `python -m pytest -q -p no:cacheprovider --no-header tests/test_catalog_filters.py::test_api_available_only_is_forwarded tests/test_catalog_filters.py::test_api_topic_and_available_pagination tests/test_catalog_filters.py::test_available_only_excludes_checked_out_books tests/test_catalog_filters.py::test_filters_apply_before_pagination tests/test_catalog_filters.py::test_topic_and_available_filters_combine_with_and tests/test_catalog_filters.py::test_topic_filter_is_case_insensitive tests/test_catalog_filters.py::test_topic_filter_returns_only_matching_topic tests/test_catalog_filters.py::test_unknown_topic_returns_empty_page` | 1 | 0 | 8 | `baseline-target.log` |
| 修改前回归测试 | `python -m pytest -q -p no:cacheprovider --no-header tests/test_api_contract.py::test_boolean_spellings_are_accepted tests/test_api_contract.py::test_empty_query_returns_first_page tests/test_api_contract.py::test_invalid_available_only_returns_400 tests/test_api_contract.py::test_invalid_paging_returns_400 tests/test_catalog_contract.py::test_api_payload_shape_is_unchanged tests/test_catalog_contract.py::test_default_listing_keeps_title_then_id_order tests/test_catalog_contract.py::test_default_listing_returns_every_seed_book tests/test_catalog_contract.py::test_page_shape_is_unchanged tests/test_pagination.py::test_default_page_size_is_twenty tests/test_pagination.py::test_invalid_page_raises_value_error tests/test_pagination.py::test_invalid_page_size_raises_value_error tests/test_pagination.py::test_maximum_page_size_is_allowed tests/test_pagination.py::test_page_beyond_the_end_returns_empty_items tests/test_pagination.py::test_second_page_starts_after_the_first_page` | 0 | 23 | 0 | `baseline-regression.log` |
| 修改后目标测试 | `python -m pytest -q -p no:cacheprovider --no-header tests/test_catalog_filters.py::test_api_available_only_is_forwarded tests/test_catalog_filters.py::test_api_topic_and_available_pagination tests/test_catalog_filters.py::test_available_only_excludes_checked_out_books tests/test_catalog_filters.py::test_filters_apply_before_pagination tests/test_catalog_filters.py::test_topic_and_available_filters_combine_with_and tests/test_catalog_filters.py::test_topic_filter_is_case_insensitive tests/test_catalog_filters.py::test_topic_filter_returns_only_matching_topic tests/test_catalog_filters.py::test_unknown_topic_returns_empty_page` | 0 | 8 | 0 | `attempt-1-target.log` |
| 修改后回归测试 | `python -m pytest -q -p no:cacheprovider --no-header tests/test_api_contract.py::test_boolean_spellings_are_accepted tests/test_api_contract.py::test_empty_query_returns_first_page tests/test_api_contract.py::test_invalid_available_only_returns_400 tests/test_api_contract.py::test_invalid_paging_returns_400 tests/test_catalog_contract.py::test_api_payload_shape_is_unchanged tests/test_catalog_contract.py::test_default_listing_keeps_title_then_id_order tests/test_catalog_contract.py::test_default_listing_returns_every_seed_book tests/test_catalog_contract.py::test_page_shape_is_unchanged tests/test_pagination.py::test_default_page_size_is_twenty tests/test_pagination.py::test_invalid_page_raises_value_error tests/test_pagination.py::test_invalid_page_size_raises_value_error tests/test_pagination.py::test_maximum_page_size_is_allowed tests/test_pagination.py::test_page_beyond_the_end_returns_empty_items tests/test_pagination.py::test_second_page_starts_after_the_first_page` | 0 | 23 | 0 | `attempt-1-regression.log` |
| 修改后全量测试 | `python -m pytest -q -p no:cacheprovider --no-header` | 0 | 32 | 0 | `full-suite.log` |

同一组目标测试在修改前因功能未实现而失败（退出码 1，存在真实断言失败），修改后全部通过；回归测试在修改前后均通过。
