---
spec: BOOK-CATALOG
version: 4
status: active
applies_to:
  - src/booknest/catalog.py
  - src/booknest/models.py
---
# 馆藏目录规格 BookNest Catalog Specification

本文件是 `GET /books` 列表行为的有效规格来源。所有条目均由验收测试覆盖；
未在本文声明的行为不属于本次任务的授权范围。

## [BOOK-001] 默认排序

列表必须按 `title` 升序排列；当 `title` 完全相同时，按 `id` 升序排列。
排序必须稳定，且不受筛选参数影响。调用方不传任何筛选参数时，返回顺序必须与
本规格引入前完全一致。

## [BOOK-002] 分页契约

- `page` 从 1 开始计数，默认值为 1。
- `page_size` 默认值为 20，允许的取值范围是 1 到 50（含边界）。
- `page` 小于 1、`page_size` 小于 1 或大于 50 时，服务层抛出 `ValueError`，
  HTTP 层返回 400。
- 分页必须作用在筛选后的结果集上：先筛选、再排序、最后切页。
- `total` 表示当前筛选条件下全部结果的数量，而不是当前页的条数。

## [BOOK-003] 列表响应结构

列表结果由 `items`、`page`、`page_size`、`total` 四个字段组成。`items` 中每个元素
保留 `id`、`title`、`author`、`topic`、`published_year`、`copies_total`、
`copies_available` 七个字段。字段名、类型与嵌套结构不得改变。

## [BOOK-004] 主题与在架筛选

本条目是 v4 修订版，对应任务 `TASK-BOOK-0042`：

- `topic`：主题 slug 的精确匹配。比较前必须先做 Unicode NFC 归一化，再去除
  首尾空白并忽略大小写（casefold）。空字符串或未提供等同于不筛选。未知主题
  返回空结果，而不是错误。
- `available_only`：为 `true` 时仅保留 `copies_available > 0` 的书；
  为 `false` 或缺省时不做在架过滤。布尔值也接受 `1/0`、`yes/no`、`on/off`。
- 两个筛选参数同时出现时，结果取交集（AND 语义）。
- 筛选必须先于排序和分页执行，`total` 必须反映筛选后的总数。
- 新筛选不得改变 `BOOK-001` 的排序、`BOOK-002` 的分页校验与
  `BOOK-003` 的响应结构。

## [BOOK-005] 边界与错误

- 未知 `topic`：返回 200 与空 `items`，`total` 为 0，不抛出错误。
- 非法 `page` / `page_size` / `available_only`：沿用 `API-002` 的 400 响应。
- 目录为空、页码越界：返回 200 与空 `items`，`total` 为 0 或筛选后总数。

## [BOOK-006] 筛选后的排序稳定性

筛选不得打乱 `BOOK-001` 定义的顺序。对同一个 `topic` 的两次连续请求，如果
底层馆藏未变，返回的 `items` 顺序必须完全一致；分页边界上的记录不得重复或
遗漏。
