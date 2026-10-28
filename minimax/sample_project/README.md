# BookNest · SDD 验证样例工程

一个可运行、带测试的迷你业务工程，用于验证 SpecAnchor 上下文模块：

- `specs/`：有效规格（`BOOK-*`、`API-*`、`ADR-*`、无关的 `REPORT-*`）
- `src/booknest/`：实现（`catalog` 列表服务、`api` HTTP 适配器、`reports` 报表）
- `tests/`：目标功能测试与回归测试

## 任务

`TASK-BOOK-0042`：为 `GET /books` 增加 `topic` 与 `available_only` 筛选，
要求先筛选再分页，且不改变默认排序、分页校验与响应结构。

## 运行

```bash
python -m pytest -q
```

当前提交为**修改后**状态：全部测试通过。修改前（目标功能未实现）的基线
文件快照在 `../evidence/baseline/`，可用 `../scripts/verify_change.py` 复现
"修改前目标测试失败、回归测试通过；修改后全部通过"。

## 目录

```text
sample_project/
├── specs/                 # 规格与 ADR
├── src/booknest/          # 业务代码
├── tests/                 # 目标测试 / 回归测试
└── pytest.ini
```
