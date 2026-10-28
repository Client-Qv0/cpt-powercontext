# 证据目录说明

本目录保存可复核的技术使用记录。所有文件由真实运行生成，不是手写样例。

## 当前已提交

| 路径 | 内容 |
| --- | --- |
| `baseline/sample_project.zip` | 修改前完整工程快照（由 `scripts/reset_demo.py --baseline` 使用） |
| `baseline/manifest.json` | 快照逐文件 SHA-256 与文件数 |
| `spec-update.json` | 规格 v3 → v4 重新导入后的前后对比（`python -m specanchor spec-update` 生成） |

## 运行 `apply` 后生成

| 路径 | 内容 |
| --- | --- |
| `runs/<timestamp>-TASK-BOOK-0042-<run_id>/` | 上下文、提示词、MiniMax 原始响应、补丁、测试日志、PowerContext 状态、结果摘要 |
| `patches/TASK-BOOK-0042.patch` | 最终应用的补丁（与 `sample_project` 的代码差异对应） |
| `test-logs/before-target.log` 等 | `scripts/verify_change.py` 生成的修改前/后测试日志（头部含命令、退出码、代码版本） |
| `verify-change.json` | 修改前失败 / 修改后通过的机器可读汇总 |
| `minimax-development-record.md` | MiniMax 开发记录（任务、上下文来源、调用、补丁、测试） |
| `seekdb-queries.md` | 本次上下文构建实际执行的 SQL 与检索结果 |
| `powercontext-state.md` | Scope、contract/outcome、done/todo/verification 与重启复用说明 |
| `test-results.md` | 修改前后测试命令、退出码与代码版本 |

## 一键生成

```bash
python -m specanchor apply --task examples/task-book-filters.json
python scripts/verify_change.py
python scripts/render_evidence.py
```

`render_evidence.py` 会自动选择最近一次 `status=succeeded` 的运行目录；
也可以显式传 `--run-dir evidence/runs/<...>`。
