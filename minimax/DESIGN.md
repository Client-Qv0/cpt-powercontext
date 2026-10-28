# SpecAnchor 一页技术说明

> 面向软件持续演进的 SDD 上下文管理：把“这次任务该遵守什么、该改哪里、怎么证明没改坏”变成一次可复现的检索与验证流程。

## 1. 模块结构

```text
                 ┌──────────────────────────────┐
   task.json ───▶│ specanchor context           │
                 │  ├─ tokenize(query)          │
                 │  ├─ BM25 over seekdb terms   │──▶ context.json
                 │  ├─ traceability boosts      │    (specs / code / tests /
                 │  ├─ source existence check   │     state / sources / SQL)
                 │  └─ PowerContext continuity  │
                 └──────────────┬───────────────┘
                                │
                 ┌──────────────▼───────────────┐
                 │ specanchor apply             │
                 │  baseline tests → MiniMax    │──▶ patch + tests + evidence
                 │  diff guard → git apply      │
                 │  target/regression → retry   │
                 │  TaskOutcome → PowerContext  │
                 └──────────────┬───────────────┘
                                │
        seekdb: 规格分节 / AST 符号 / 测试 covers+imports / 词项
        PowerContext: WorkContract + TaskOutcome + continuity
```

`sample_project` 是独立的、可运行的 BookNest 馆藏服务；上下文模块不 import 业务代码，
只通过文件与 AST 建立索引，因此可以换成任意 Python 工程。

## 2. 上下文选择方式

1. **导入**：Markdown 规格按 `## [SPEC-ID]` 分节，保留路径、行号、哈希、修订号；
   Python 源码用 `ast` 拆成 module/class/function/method，保留签名、源码、docstring；
   pytest 文件按测试函数拆分，记录 docstring 中的 `覆盖/covers` 与模块 `import`。
2. **索引**：规格/代码/测试的文本统一 tokenize（英文标识符拆分、中文 bigram），写入 `sa_terms` 倒排表；
   同时把规格 frontmatter 的 `applies_to` 写入 `sa_spec_targets`。
3. **检索**：对任务标题、需求、focus、must-preserve 加权，按 BM25 从 `sa_terms` 取候选；
   再叠加可解释的 traceability 加权：任务显式引用的规格 ID、标题命中、`applies_to` 路径、任务点名符号。
4. **测试分组**：目标规格（任务声明的 `target_specs`）∩ 测试 `covers` = 目标测试；
   导入受影响模块的其余测试 = 回归测试。两组互斥。
5. **来源校验**：返回前逐条检查路径存在、行号不越界，并计算文件 SHA-256 写入 `sources`。
6. **不固定答案**：规格重新导入会生成新 revision 并停用旧 revision；下一次 `context` 读取的是新正文，
   `context_digest` 随内容变化（`test_spec_update_is_used_after_reimport` 覆盖）。

选择过程的核心 SQL、候选数、BM25 参数与命中词都写入 `diagnostics`，便于复核“为什么是这些来源”。

## 3. 规格演进

`sa_spec_sections` 以 `(project, doc_path, section_key, revision)` 为唯一键；导入时：

- 内容哈希未变 → 只更新行号/导入时间，不产生新 revision；
- 内容变化 → 旧行 `active=0`，插入 `revision+1`，并写 `sa_spec_changes`；
- 文档中删除的条目 → 置为 inactive。

检索只读 `active=1`，所以旧规格不会继续污染上下文；历史仍可审计。
`spec-update` 样例把 `BOOK-004` 从 v3 改到 v4（新增 NFC 归一化），验证 revision 1→2、
哈希变化、上下文正文变化、旧修订停用。

## 4. 任务状态（PowerContext）

每次 `apply`：

- `WorkContract`：objective、`in_scope`（候选代码路径）、`completion_criteria`
  （目标测试先失败后通过、回归通过、只改 `src/`）；
- `TaskOutcome`：status、observations（上下文规模、基线失败、模型尝试、补丁、测试通过数）、
  checks（baseline.target / target.tests / regression.tests / full.suite）、remaining_work；
- 两者作为 PowerContext Source 捕获在项目 Scope 中，`SourceRef` 写回结果 JSON。

`context` / `state show` 是独立进程：重新打开同一个 `.state/powercontext.db`，调用
`work.continuity()` 读事件，再通过 `records.get_source` 读回完整记录，投影成
`done / todo / verification`。因此“重启后读取并使用状态”不依赖任何进程内缓存。

## 5. MiniMax 接入与安全边界

- `POST {MINIMAX_BASE_URL}/chat/completions`，模型 `MiniMax-M3.1-Flash`，`reasoning_effort=high`；
  只记录 content 摘要、usage、时延，不保存私有思维链，也不写 API Key。
- 提示词包含：任务、必须保持项、检索到的规格全文、待改代码完整文件、目标测试源码、回归测试清单、
  PowerContext 状态；要求只输出 unified diff。
- 程序侧硬约束：路径必须 `src/` 前缀；拒绝 `tests/`、`specs/`、绝对路径、`..`、二进制补丁；
  应用前 `git apply --check`；测试失败先回滚再带日志重试；最多 3 次。
- 目标测试与回归测试的 nodeid 来自上下文，不由模型决定；测试文件在修改前后保持一致。

## 6. 成本与时延

- 上下文全文约 15–25 KB（9 条规格 + 8 个符号 + 8 个目标测试）；一次成功的修改通常 1 次模型调用；
  重试只在测试失败时发生。
- 检索为纯 SQL + 本地 BM25，`context` 在本机约 0.1–0.3 s；PowerContext 启停约 1 s。
- 无 embedding / 向量服务依赖，离线可复现（除 MiniMax 调用本身）。

## 7. 验收对应

| 要求 | 实现 |
| --- | --- |
| 明确入口与输入输出 | `python -m specanchor`；`context` 输出 `specanchor.context.v1` JSON + Markdown |
| 定位规格/代码/测试 | `specs[] / code[] / tests.target[] / tests.regression[]`，均带真实路径与行号 |
| 规格更新后使用新内容 | revision + active 机制；`spec-update` 验证样例 |
| 数据库实际参与 | `diagnostics.db.queries`；`evidence/seekdb-queries.md` |
| 状态保存与复用 | WorkContract/TaskOutcome/continuity；`state show` 独立进程读取 |
| MiniMax 实际参与 | `apply` 的调用日志、原始响应、补丁、测试日志、开发记录 |
| 修改有效 | 同一组目标测试修改前 8 failed、修改后 8 passed；回归 23 passed |
