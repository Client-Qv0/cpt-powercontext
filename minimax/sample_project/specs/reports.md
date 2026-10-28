---
spec: BOOK-REPORTS
version: 1
status: active
applies_to:
  - src/booknest/reports.py
---
# 运营报表规格

本规格描述后台月度报表，与 `GET /books` 列表接口无关。保留该规格是为了让
上下文模块必须依据任务语义排除无关资料，而不是把全部文档都塞进上下文。

## [REPORT-001] 月度借阅报表

每月 1 日生成上月借阅报表，字段包括 `titles`、`topics` 与
`available_titles`。报表按 `topic` 字典序输出，只读，不修改馆藏数据。

## [REPORT-002] 报表导出

报表支持 CSV 与 JSON 两种导出格式，文件名格式为
`booknest-report-YYYY-MM.csv`。导出失败时返回 500 并记录审计日志。
