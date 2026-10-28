---
spec: BOOK-API
version: 2
status: active
applies_to:
  - src/booknest/api.py
---
# BookNest HTTP 契约

该契约描述对外暴露的 `GET /books` 接口。HTTP 框架不在本样例范围内，
`booknest.api.list_books_response` 是与之等价的适配器。

## [API-001] GET /books 查询参数

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `page` | integer | 1 | 页码，必须大于等于 1 |
| `page_size` | integer | 20 | 每页条数，1 到 50 |
| `topic` | string | 无 | 主题 slug，大小写不敏感，空串视为未提供 |
| `available_only` | boolean | false | 仅返回可借复本大于 0 的书 |

布尔参数接受 `1/0`、`true/false`、`yes/no`、`on/off`（忽略大小写）。
其余取值返回 400。

## [API-002] 错误响应

参数校验失败时返回状态码 400，响应体为 `{"error": "<reason>"}`。
未知 `topic` 不是错误，必须返回 200 与空列表；服务端不得因为筛选没有命中
而返回 404。

## [API-003] 响应结构

成功响应状态码为 200，响应体包含 `items` 数组以及 `page`、`page_size`、
`total` 三个整数。`items` 的元素字段与 `BOOK-003` 一致。

## [API-004] 兼容性

已存在的调用方只使用 `page` 与 `page_size`。新增参数不得改变既有请求的
响应结构、默认分页大小、错误码和排序顺序。
