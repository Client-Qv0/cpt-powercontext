# seekdb / OceanBase 使用记录

- 生成时间：2026-10-29T08:07:51+08:00
- 引擎：seekdb/OceanBase (MySQL protocol)
- 数据库：`specanchor`
- 索引内容：9 条规格、8 个代码符号、22 个测试（选入本次上下文）

## 1. 本次上下文构建实际执行的查询

| # | 行数 | 耗时(ms) | SQL |
| ---: | ---: | ---: | --- |
| 1 | 238 | 24.69 | `SELECT ref_id, term, tf FROM sa_terms WHERE project=%s AND kind=%s AND term IN (%s×144)` |
| 2 | 103 | 19.384 | `SELECT term, COUNT(DISTINCT ref_id) AS df FROM sa_terms WHERE project=%s AND kind=%s AND term IN (%s×144) GROUP BY term` |
| 3 | 12 | 6.097 | `SELECT id, token_count FROM sa_spec_sections WHERE project=%s AND active=1` |
| 4 | 12 | 7.328 | `SELECT id, doc_path, section_key, spec_id, heading, level, line_start, line_end, body, revision, content_hash, token_count FROM sa_spec_sections WHERE project=%s AND active=1` |
| 5 | 85 | 7.77 | `SELECT ref_id, term, tf FROM sa_terms WHERE project=%s AND kind=%s AND term IN (%s×144)` |
| 6 | 20 | 5.071 | `SELECT term, COUNT(DISTINCT ref_id) AS df FROM sa_terms WHERE project=%s AND kind=%s AND term IN (%s×144) GROUP BY term` |
| 7 | 18 | 5.852 | `SELECT id, token_count FROM sa_code_symbols WHERE project=%s AND active=1` |
| 8 | 4 | 6.933 | `SELECT target_path FROM sa_spec_targets WHERE project=%s AND doc_path IN (%s×3)` |
| 9 | 18 | 6.816 | `SELECT id, path, module, qualname, kind, signature, lineno, end_lineno, source, docstring, revision, content_hash FROM sa_code_symbols WHERE project=%s AND active=1` |
| 10 | 23 | 8.284 | `SELECT id, path, test_id, qualname, kind, lineno, end_lineno, source, docstring, covers, imports, revision, content_hash FROM sa_tests WHERE project=%s AND active=1` |

## 2. 检索得到的规格（来自 `sa_spec_sections`）

| 规格 | 路径 | 修订 | 内容哈希 | 得分 |
| --- | --- | ---: | --- | ---: |
| `BOOK-004` | `specs/catalog.md:35-47` | 1 | `0b154f8abff6a76f…` | 205.2653 |
| `API-001` | `specs/api.md:13-24` | 1 | `28116adf9a9cf3f9…` | 109.8119 |
| `BOOK-005` | `specs/catalog.md:48-52` | 1 | `c8dd72c7d912aeed…` | 44.1547 |
| `ADR-0008` | `specs/decisions/ADR-0008.md:10-19` | 1 | `bcf1fd9f800cf078…` | 101.6078 |
| `BOOK-001` | `specs/catalog.md:14-19` | 1 | `c65fce1f2603d1fd…` | 67.7696 |
| `BOOK-002` | `specs/catalog.md:20-28` | 1 | `476fc307b06596ba…` | 47.2211 |
| `BOOK-003` | `specs/catalog.md:29-34` | 1 | `43c01bd1c7f759a1…` | 45.4818 |
| `API-004` | `specs/api.md:36-39` | 1 | `5b76b25873b076e7…` | 43.1816 |
| `API-002` | `specs/api.md:25-30` | 1 | `1319eb0b2f017577…` | 41.6392 |

## 3. 检索得到的代码符号（来自 `sa_code_symbols`）

| 符号 | 路径 | 修订 | 得分 |
| --- | --- | ---: | ---: |
| `CatalogService.list_books` | `src/booknest/catalog.py:23-47` | 1 | 63.3041 |
| `list_books_response` | `src/booknest/api.py:20-37` | 1 | 52.5549 |
| `_page_payload` | `src/booknest/api.py:60-77` | 1 | 35.437 |
| `CatalogService` | `src/booknest/catalog.py:17-54` | 1 | 21.5776 |
| `booknest.catalog` | `src/booknest/catalog.py:1-54` | 1 | 18.5467 |
| `_parse_bool` | `src/booknest/api.py:49-57` | 1 | 16.0195 |
| `CatalogService._validate_paging` | `src/booknest/catalog.py:50-54` | 1 | 14.551 |
| `CatalogService.__init__` | `src/booknest/catalog.py:20-21` | 1 | 14.2555 |

> 行号、内容和哈希均通过 `SpecAnchor._verify_sources` 对真实文件校验；`context.sources` 记录了每个文件的 SHA-256。
