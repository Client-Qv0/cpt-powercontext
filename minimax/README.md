# SpecAnchor · 规有所依

面向软件持续演进的 **SDD（Spec-Driven Development）上下文管理系统**，为 AI 开发助手回答三个问题：

1. 这次任务应遵守哪些**当前有效**的规格？
2. 应该修改哪些代码文件 / 符号？
3. 用哪些测试验证新功能、哪些测试保护原有行为？

并用一次真实的局部代码修改证明上下文模块有效。技术栈：**MiniMax（代码修改）+ seekdb（工程资料与索引）+ PowerContext（任务状态）**。

---

## 0. 当前交付状态与复现方式

仓库中的 `sample_project/` 已包含真实 MiniMax 运行生成的修复。请先查看
`evidence/runs/20261029-080429-TASK-BOOK-0042-run-ca941f5461/` 和修改前后日志。
当前样例目标测试 8 passed、回归 23 passed、全量 32 passed。`evidence/` 中的全部记录来自一次
**真实的 MiniMax 调用**（2026-10-29，`MiniMax-M3.1-Flash`）。

**不调用模型的复核**（无需 API Key、无需数据库，也不覆盖当前工程）：

```bash
python scripts/replay_evidence.py --run-dir evidence/runs/20261029-080429-TASK-BOOK-0042-run-ca941f5461
```

它在临时独立 Git 仓库中解压修改前快照，验证目标失败与回归通过，应用保存的
MiniMax 补丁，再验证目标、回归及全量测试。该过程是历史补丁复现，不能冒充新的模型调用，
也不会恢复或伪造 PowerContext 状态。

**其余环节复核**（需要 seekdb；不需要 MiniMax 密钥）：

| 验证项 | 命令 |
| --- | --- |
| 模块可运行、数据库接入 | `python -m specanchor doctor` |
| 上下文正确性 | `python -m specanchor context --task examples/task-book-filters.json` |
| 修改前失败 / 修改后通过 | `python scripts/verify_change.py` |
| 规格更新后使用新内容 | `python -m specanchor spec-update --task examples/task-book-filters.json` |
| 状态保存与重启复用 | `python -m specanchor verify --task examples/task-book-filters.json --record`，再 `python -m specanchor state show --task examples/task-book-filters.json` |
| 由 MiniMax 重新生成补丁 | `python -m specanchor apply --task examples/task-book-filters.json`（需要 key） |

`apply` 的复现顺序是“修改前基线 → MiniMax 生成补丁 → 应用 → 跑测试”：

```bash
python scripts/reset_demo.py --baseline --yes   # 回到修改前基线（目标测试 8 failed）
python -m specanchor apply --task examples/task-book-filters.json
python scripts/verify_change.py
python scripts/render_evidence.py
```

`apply` 成功后会在 `evidence/runs/<时间>-TASK-BOOK-0042-<id>/` 留下上下文、提示词、
模型响应、补丁、日志和 PowerContext 状态，并把 `sample_project` 更新为通过状态。

**重新调用模型演示**（需要自己配置 API Key 和 seekdb）：请复制整个 `minimax/` 目录到
新的演示目录，在副本中按第 8 节初始化并执行 `python scripts/reset_demo.py --baseline`、
`python -m specanchor ingest --project booknest`，再执行 `apply`。
副本中的 `.env` 应使用独立数据库名，并将 `SPECANCHOR_STATE_DIR=./.state`、
`SPECANCHOR_PROJECT_ROOT=./sample_project`，避免连接原工程状态。
不要在已修复的交付工程里直接 `apply`：目标测试已通过时，程序会拒绝把它当成有效修改样本。

升级已有索引时，先运行 `python -m specanchor db init` 创建新增的来源指纹表，
再运行 `ingest`。`context` 会拒绝尚未导入的文件修改、增加或删除，提示重新导入。

---

## 1. 作品结构

```text
minimax/
├── specanchor/                 # 上下文模块（CLI）
│   ├── cli.py                  # 入口：db/ingest/context/state/apply/verify/spec-update/doctor
│   ├── db.py                   # seekdb / OceanBase 连接、SQL 追踪
│   ├── schema.sql              # 12 张索引表（规格、代码、测试、词项、变更审计…）
│   ├── ingest.py               # 规格分节、Python AST 符号、pytest 用例与 covers/imports 导入
│   ├── retrieve.py             # BM25 检索 + 可追溯性加权 + 来源校验 + 上下文组装
│   ├── state.py                # PowerContext Work contract / Task outcome / continuity
│   ├── minimax.py              # MiniMax OpenAI 兼容 HTTP 客户端
│   ├── prompts.py              # SDD 提示词（规格 + 代码 + 测试 + 不变量）
│   ├── patch.py                # unified diff 提取、路径安全校验、git apply
│   └── agent.py                # 端到端：基线失败 → MiniMax → 应用 → 目标/回归 → 记录状态
├── sample_project/             # 可运行业务工程（BookNest 馆藏目录）
│   ├── specs/                  # BOOK-* / API-* / ADR-* 与无关的 REPORT-*（干扰项）
│   ├── src/booknest/           # catalog / api / reports
│   └── tests/                  # 8 个目标测试 + 23 个回归用例
├── examples/
│   ├── task-book-filters.json  # 验证样例任务
│   └── spec-update/catalog-v4.md
├── scripts/
│   ├── verify_change.py        # 修改前失败 / 修改后通过 的独立证明
│   ├── render_evidence.py      # 从真实运行产物生成技术记录
│   └── reset_demo.py           # 恢复基线并清空本地状态
├── evidence/                   # 运行后生成的证据（基线快照已提交）
├── tests/                      # 上下文模块自身的 31 项测试（验收/来源指纹/证据一致性/补丁安全/客户端）
├── requirements.txt
└── README.md / DESIGN.md
```

---

## 2. 三项指定技术各自承担什么

| 技术 | 在流程中的实际作用 | 关键代码 / 证据 |
| --- | --- | --- |
| **MiniMax** | `specanchor apply` 把任务、有效规格、待改代码、目标/回归测试和“必须保持”的约束发给 `MiniMax-M3.1-Flash`，由模型生成 unified diff；程序校验路径（只允许 `src/`）、应用补丁、跑测试，失败时带着日志重试。开发记录保存请求摘要、模型/用量/时延、响应补丁与对应测试结果 | `specanchor/minimax.py`、`prompts.py`、`agent.py`、`evidence/minimax-development-record.md` |
| **seekdb / OceanBase** | 存储并检索全部工程资料：规格按 `## [SPEC-ID]` 分节入库；Python 源码用 AST 拆成模块/类/函数/方法；pytest 用例记录 `covers` 与 `imports`；重建词项倒排索引。上下文构建的每一次规格/代码/测试检索都是 SQL 查询，结果直接进入上下文 | `specanchor/schema.sql`、`ingest.py`、`retrieve.py`、`evidence/seekdb-queries.md` |
| **PowerContext** | 用原生 Work 循环保存任务：`WorkContract` 记录目标/范围/完成标准；`TaskOutcome` 记录已完成事项、验证 checks 与待办；`continuity()` 在后续独立进程里读回。`context` 输出中的“已完成/待办/验证结果”即来自这里 | `specanchor/state.py`、`evidence/powercontext-state.md` |

seekdb 实际用于检索：`context` 的 `diagnostics.db.queries` 和 `evidence/seekdb-queries.md` 会列出本次检索实际执行的 SQL、行数与耗时。
PowerContext 也不是可选项：`apply` 成功/失败都会写 `TaskOutcome`，`context` / `state show` 会在新进程中读回。

---

## 3. 环境与版本

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| Python | 3.12.16 | 3.11+ 可用；本机实测 3.12 |
| seekdb | 1.4.0.0 | OceanBase seekdb，MySQL 协议 `127.0.0.1:2881` |
| PowerContext | 1.4.1 | `powercontext[builtin]`，builtin runtime + SQLite 状态库 |
| PyMySQL | 1.2.0 | 访问 seekdb / OceanBase |
| httpx | 0.28.1 | 调用 MiniMax |
| pytest | 8.4.2 | 业务工程与模块测试 |
| MiniMax | `MiniMax-M3.1-Flash` | OpenAI 兼容接口 `https://api.minimax.cn/v1` |

---

## 4. 启动 seekdb

本仓库不提交 seekdb 二进制（体积与平台相关）。任选一种方式：

### 4.1 本机二进制（本作品实测方式）

从 [oceanbase/seekdb](https://github.com/oceanbase/seekdb) 获取 1.4.0 版本并构建 / 下载对应平台二进制，然后：

```bash
mkdir -p ./seekdb-data
./seekdb --nodaemon --base-dir ./seekdb-data --port 2881
```

Windows（在本机实测）：

```powershell
.\seekdb.exe --nodaemon --base-dir F:\path\to\seekdb-data --port 2881
```

首次启动会自动初始化数据目录，默认用户 `root`、空密码。
用 `python -m specanchor doctor` 验证连接。

### 4.2 已有 OceanBase / seekdb

如果评测环境已提供实例，设置：

```bash
export SPECANCHOR_DB_HOST=127.0.0.1
export SPECANCHOR_DB_PORT=2881
export SPECANCHOR_DB_USER=root
export SPECANCHOR_DB_PASSWORD=
export SPECANCHOR_DB_NAME=specanchor
```

`db init` 会创建数据库与表；不需要手工建表。

---

## 5. 安装

```bash
cd minimax
python -m venv .venv

# Windows
.venv\Scripts\python -m pip install -r requirements.txt
# Linux / macOS
.venv/bin/python -m pip install -r requirements.txt

cp .env.example .env        # Windows: copy .env.example .env
# 编辑 .env，至少确认 seekdb 连接；apply 前填 MINIMAX_API_KEY
```

> `requirements.txt` 固定 `powercontext[builtin]==1.4.1`，与 PyPI 发布版本一致。
> 如果评测机不能联网，请预先准备 wheel；模块本身不需要下载模型或额外数据。

---

## 6. 初始化数据

```bash
# 1) 建库建表
python -m specanchor db init

# 2) 导入工程资料到 seekdb，重建词项索引
python -m specanchor ingest --project booknest

# 3) 清空本地 PowerContext 状态（从空状态开始）
python -m specanchor state reset
```

`ingest` 输出示例：`spec_sections=12, code_symbols=18, tests=23, terms≈1900`。
`sa_spec_sections` 按 `[SPEC-ID]` 分节；`sa_code_symbols` 来自 AST；`sa_tests` 记录 `covers` 与 `imports`；
`sa_spec_changes` 记录规格修订；`sa_import_runs` 记录每次导入。

---

## 7. 调用入口与输出

入口是 CLI：`python -m specanchor <command>`。核心命令：

### 7.1 `context`：为任务构建上下文

```bash
python -m specanchor context --task examples/task-book-filters.json
python -m specanchor context --task examples/task-book-filters.json --json --out evidence/context.json
python -m specanchor context --task examples/task-book-filters.json --trace
```

输出 JSON（`schema=specanchor.context.v1`）字段：

| 字段 | 内容 |
| --- | --- |
| `task` | 任务 id、标题、原始需求、必须保持项 |
| `specs[]` | `spec_id`、`path`、`heading`、`line_start/line_end`、`revision`、`content_hash`、`score`、`why`、`text` |
| `code[]` | `path`、`qualname`、`kind`、`signature`、行号、`content_hash`、`score`、`why`、`source` |
| `tests.target[]` | 覆盖目标规格的测试；含 `path`、`test_id`、`covers`、`why`、`source` |
| `tests.regression[]` | 导入受影响模块的兼容性测试；同一测试不会同时出现在两组 |
| `state` | PowerContext 读回的 `scope_id`、contract、latest_outcome、`done`、`todo`、`verification`、events |
| `sources[]` | 所有被引用文件的真实路径、是否存在、文件 SHA-256、行数 |
| `diagnostics` | 查询词、BM25 统计、seekdb 实际 SQL 列表 |
| `context_digest` | 规格/代码/测试内容哈希的稳定摘要 |

`render_markdown()` 同时提供人读版本（默认输出）。
所有来源在返回前由 `_verify_sources` 校验存在与行号范围；`sources` 中的 SHA-256 可独立复核。

### 7.2 `apply`：由 MiniMax 完成代码修改

```bash
python -m specanchor apply --task examples/task-book-filters.json
# 只调用模型、校验补丁，不落盘：
python -m specanchor apply --task examples/task-book-filters.json --dry-run
```

流程：

1. 构建上下文，从 PowerContext 读取（或创建）Work contract；
2. 跑目标测试，**要求修改前失败**（退出码 1 且有真实断言失败；环境错误会中止）；
3. 跑回归测试，要求修改前通过；
4. 调用 MiniMax；提取 unified diff；**按 hunk 正文修正 `@@ -a,b +c,d @@` 的行数**
   （模型常给出看似合理但与正文不符的计数，`git apply` 会直接拒绝整份补丁）；
   拒绝 `src/` 之外的路径、测试/规格修改与二进制补丁；
5. `git apply` 后跑目标 + 回归；失败则回滚补丁，把失败日志发回模型重试（默认最多 3 次）；
   补丁本身无法应用时同样回到重试流程，而不是直接终止整次运行；
6. 成功后跑全量测试，写 `TaskOutcome` 到 PowerContext，保存 `evidence/runs/<...>/`；
7. 打印运行摘要（JSON）。

产物目录：

```text
evidence/runs/<timestamp>-TASK-BOOK-0042-<run_id>/
├── context.json               # 提供给 MiniMax 的完整上下文
├── prompt.md                  # 发给模型的提示词（不含密钥）
├── minimax-calls.jsonl        # 请求摘要、模型、用量、时延
├── minimax-response-1.txt    # 原始响应
├── attempt-1.diff             # 提取并校验后的补丁
├── attempt-1.hunk-normalization.json  # @@ 行数被修正时的记录（若有）
├── baseline-target.log        # 修改前目标测试（预期失败）
├── baseline-regression.log
├── attempt-1-target.log
├── attempt-1-regression.log
├── full-suite.log
├── powercontext-contract.json
├── powercontext-outcome.json
├── powercontext-state.json    # 重启后可读的状态投影
└── result.json
```

### 7.3 `state`：任务状态

```bash
python -m specanchor state show --task examples/task-book-filters.json
python -m specanchor state reset
```

`state show` 是独立进程，会重新打开 `.state/powercontext.db` 并通过 `Work continuity` 读回记录，
因此可以作为“重启模块后读取并使用状态”的直接证据。

### 7.4 `verify`：不调用模型，独立跑目标/回归

```bash
python -m specanchor verify --task examples/task-book-filters.json
python -m specanchor verify --task examples/task-book-filters.json --record
```

`--record` 会把这次验证结果作为新的 `TaskOutcome` 写入 PowerContext。

### 7.5 `spec-update`：规格变更后重新导入

```bash
python -m specanchor spec-update --task examples/task-book-filters.json
```

它在 `.state/spec-update-demo/` 复制样例工程，先导入 v3 规格并构建上下文，再用
`examples/spec-update/catalog-v4.md` 替换 `specs/catalog.md`，重新导入并构建上下文。
输出并写入 `evidence/spec-update.json` 的内容包括：

- `BOOK-004` 修改前后的 `revision`（1 → 2）、`content_hash`、完整文本；
- `sa_spec_changes` 中检测到的变更；
- 前后 `context_digest` 与 SQL 查询条数。

断言：修改后上下文包含 v4 的“NFC 归一化”等新条款，且不再包含 v3 的旧表述；旧修订被置为 `active=0`。

### 7.6 `doctor`

```bash
python -m specanchor doctor
```

检查 seekdb 连接、`sa_*` 表数量、PowerContext 状态文件、样例工程、Git 与 MiniMax 配置（不泄露密钥）。

### 7.7 `acceptance_audit.py`：六项验收自检

```bash
python scripts/acceptance_audit.py          # 打印当前六项状态
python scripts/acceptance_audit.py --strict # 有 pending/fail 时退出非零
```

逐项检查“能够运行、上下文正确、数据库实际参与、MiniMax 实际参与、状态能够复用、
代码修改有效”，并写入 `evidence/acceptance-audit.json`（该文件默认不提交，避免把
修改前状态误当成最终结果）。

---

## 8. 完整验收流程（与评分项对应）

```bash
# 0. 环境
python -m specanchor doctor

# 1. 可运行：初始化 + 导入 + 上下文
python -m specanchor db init
python -m specanchor ingest --project booknest
python -m specanchor state reset
python -m specanchor context --task examples/task-book-filters.json --json --out evidence/context-before.json

# 2. MiniMax 实际参与 + 代码修改有效
python -m specanchor apply --task examples/task-book-filters.json

# 3. 状态复用：新进程读取
python -m specanchor state show --task examples/task-book-filters.json
python -m specanchor context --task examples/task-book-filters.json --json --out evidence/context-after.json

# 4. 修改前后独立证明（临时目录，不改工作区）
python scripts/verify_change.py

# 5. 规格更新后重新导入
python -m specanchor spec-update --task examples/task-book-filters.json

# 6. 模块自身验收测试
python -m pytest -q
```

对照表：

| 验收项 | 本作品的证据 |
| --- | --- |
| 能够运行 | 上述 0/1 步；`requirements.txt` 固定版本；seekdb 启动方式在 README；无未交付本地文件 |
| MiniMax 实际参与 | `evidence/runs/.../minimax-calls.jsonl` + `minimax-response-*.txt` + `attempt-*.diff` + `evidence/minimax-development-record.md`，补丁与 `evidence/patches/TASK-BOOK-0042.patch` 一致 |
| 上下文正确 | `context.json` 的 `specs/code/tests` + `sources` 真实路径与 SHA-256；`spec-update` 证明重新导入后使用新内容 |
| 数据库实际参与 | `diagnostics.db.queries` 与 `evidence/seekdb-queries.md`；表 `sa_spec_sections/sa_code_symbols/sa_tests/sa_terms` |
| 状态能够复用 | `apply` 写 `TaskOutcome`；`state show` / 第二次 `context` 在独立进程中读回 `done/todo/verification` |
| 代码修改有效 | `scripts/verify_change.py`：修改前目标 8 failed + 回归 23 passed；修改后目标 8 passed + 回归 23 passed + 全量 32 passed |

---

## 9. 验证样例：要改什么、哪些不能变

**任务** `TASK-BOOK-0042`：`GET /books` 增加 `topic` 与 `available_only` 筛选。

**必须实现（目标规格）**

- `BOOK-004`：`topic` 精确匹配、大小写不敏感、空串不过滤；`available_only=true` 仅返回 `copies_available > 0`；两者 AND。
- `BOOK-005`：未知主题返回 200 空列表，`total=0`。
- `API-001`：HTTP 适配器把筛选参数传入服务层。
- `ADR-0008`：筛选先于排序与分页；`total` 为筛选后总数。

**必须保持（回归约束）**

- `BOOK-001`：默认排序 `title, id`；
- `BOOK-002`：`page_size` 默认 20、范围 1..50、非法值 400；
- `BOOK-003` / `API-003`：响应字段与 `Book` 字段不变；
- `API-002` / `API-004`：既有错误码与布尔写法兼容；
- `REPORT-001`：无关的报表模块不受影响（上下文中被排除）。

**初始数据**：`sample_project/src/booknest/store.py` 中 12 本馆藏，5 个主题，9 本在架。

**上下文必须包含的来源**（可直接对照 `evidence/context-before.json` / `context-after.json`）：

| 类别 | 必须包含 | 位置 |
| --- | --- | --- |
| 规格 | `BOOK-004` 主题与在架筛选 | `specs/catalog.md:35-47` |
| 规格 | `BOOK-005` 边界与错误 | `specs/catalog.md:48-52` |
| 规格 | `API-001` 查询参数 | `specs/api.md:13-24` |
| 规格 | `ADR-0008` 筛选先于分页 | `specs/decisions/ADR-0008.md:10-19` |
| 规格（兼容约束） | `BOOK-001`、`BOOK-002`、`BOOK-003`、`API-002`、`API-004` | `specs/catalog.md`、`specs/api.md` |
| 代码 | `CatalogService.list_books` | `src/booknest/catalog.py:23-47` |
| 代码（兼容适配） | `list_books_response` | `src/booknest/api.py:20-37` |
| 目标测试 | 8 个用例：topic 精确/大小写、available_only、AND、先筛选后分页、未知主题、API 透传 | `tests/test_catalog_filters.py` |
| 回归测试 | 14 个节点 / 23 个用例 | `tests/test_api_contract.py`、`tests/test_catalog_contract.py`、`tests/test_pagination.py` |
| 应排除 | `REPORT-*`、`reports.py`、`test_reports.py`（无关报表） | 上下文不应包含 |

**操作步骤**：见第 8 节。

**预期结果**：修改前目标 8 failed、回归 23 passed；修改后目标 8 passed、回归 23 passed、全量 32 passed。

**重置方法**：

```bash
python scripts/reset_demo.py --baseline   # 用 evidence/baseline/sample_project.zip 还原修改前样例
python -m specanchor state reset          # 清空 PowerContext 状态
python -m specanchor ingest --project booknest
```

> 注意：`--baseline` 会覆盖 `sample_project/src`、`specs`、`tests`，仅用于重新演示，不要在有未提交修改时执行。

---

## 10. 测试

```bash
# 上下文模块自身（需要 seekdb 已启动）
python -m pytest -q
# 期望：31 passed

# 业务工程（apply 成功后）
cd sample_project && python -m pytest -q
# 期望：32 passed（8 目标 + 23 回归用例 + 1 报表）
```

模块测试覆盖：上下文必要来源、目标/回归互斥与覆盖范围、来源真实性与 SHA-256、
SQL 检索实际参与、规格更新后使用新内容、PowerContext 跨 runtime 重启复用；
补丁安全测试覆盖路径白名单、二进制拒绝、Markdown 围栏提取、`@@` 行数自愈与 git apply/reverse；
MiniMax 客户端测试用本地 mock HTTP 端点校验请求路径、鉴权头、请求体、响应解析与错误处理。

本机还使用同一 mock 端点跑通过完整 `specanchor apply` 链路（db init → ingest →
apply → 目标/回归/全量测试 → PowerContext → evidence），用于离线回归。

真实 MiniMax 调用已于 2026-10-29 成功完成：`MiniMax-M3.1-Flash`，1 次尝试，3547 ms，
prompt 4098 / completion 453 / total 4551 tokens；因此“真实远端模型 → 补丁 → 测试 →
状态 → 证据”的完整链路已实测。

---

## 11. 技术使用记录

以下记录已由本次真实运行（`evidence/runs/20261029-080429-TASK-BOOK-0042-run-ca941f5461`）生成，
内容全部从真实运行文件读取，不手写：

| 文件 | 内容 |
| --- | --- |
| `evidence/minimax-development-record.md` | 任务、提供的上下文来源、模型/用量/时延、完整补丁、修改前后测试表 |
| `evidence/seekdb-queries.md` | 数据库/引擎、本次实际 SQL（行数/耗时）、检索到的规格与代码 |
| `evidence/powercontext-state.md` | Scope、contract/outcome 的 SourceRef、done/todo/verification、重启复用说明 |
| `evidence/test-results.md` | 修改前后命令、退出码、passed/failed、代码版本、日志位置 |

另有：

- `evidence/baseline/sample_project.zip` + `manifest.json`：修改前完整快照与逐文件 SHA-256；
- `evidence/context-before.json` / `context-after.json`：修改前后上下文（含规格/代码/测试来源与状态）；
- `evidence/patches/TASK-BOOK-0042.patch`：MiniMax 实际补丁；
- `evidence/test-logs/`：`before-*` / `after-*` 日志，日志头包含命令、工作目录、退出码、代码版本；
- `evidence/spec-update.json`：规格更新前后对比；
- `evidence/verify-change.json`：修改前后验收的机器可读汇总；
- `evidence/acceptance-audit.json`：六项验收自检结果（6 pass）。

---

## 12. 已知限制

1. **MiniMax 密钥不在仓库中**：`apply` 需要 `MINIMAX_API_KEY`；`context`、`ingest`、`state`、`spec-update`、模块测试不需要。
2. **seekdb 二进制不提交**：按第 4 节获取；评测环境若已有 OceanBase/seekdb，直接设置 `SPECANCHOR_DB_*`。
3. **PowerContext 使用 SQLite 后端**：这是 `powercontext[builtin]` 官方支持的持久化后端；工程资料的存储/检索由 seekdb 承担，两者职责分离。若强制要求 PowerContext 也使用 OceanBase，可改用其 `oceanbase` 配置，但会引入额外部署依赖，本样例未采用。
4. **检索是确定性的 BM25 + 规则加权**，不是向量检索；中文按字符 bigram 建索引，英文按标识符拆分。选择结果可解释、可复现，且不依赖模型。
5. **`apply` 需要 Git**：用 `git apply` 应用补丁；评测机若无 Git，可手工审阅 `evidence/patches/`，但自动流程不可用。
6. **单任务单进程**：未实现并发任务调度；PowerContext 每个项目一个 Scope。
7. **本机时间**：证据时间为 `Asia/Shanghai`；不同时区运行时时间字段会变化，不影响内容哈希。

---

## 13. 许可与来源

- PowerContext SDK：Copyright 2026 OceanBase，Apache 2.0，https://github.com/oceanbase/powercontext
- seekdb：OceanBase，Apache 2.0，https://github.com/oceanbase/seekdb
- MiniMax API：https://platform.minimax.cn/
- 本作品 `sample_project` 为原创的虚构馆藏示例，不含真实个人数据或凭据。


### 复核边界

`acceptance_audit.py` 会校验已保存运行的任务、调用次数、模型信息、请求 ID、
响应与补丁的一致性及修改前后测试记录。当前是否配置密钥仅表示能否重新调用，
不会推翻已经存在的历史证据。这是本地证据一致性检查，不是远端身份认证或官方成绩。
新机器若尚未初始化数据库/导入资料/创建 PowerContext 状态，完整环境自检仍会如实报告未完成；
可先运行不依赖这些服务的 `replay_evidence.py` 核对补丁效果。
