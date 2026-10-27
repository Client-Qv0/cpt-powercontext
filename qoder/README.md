# RelayDesk 接力台

团队交接上下文管理应用，基于 PowerContext SDK 构建。

## 功能特性

- **项目管理**：创建和管理多个项目，按项目隔离数据（PowerContext Scope）
- **进展记录**：记录项目进展，支持区分进展/代码版本/评测三种记录类型（record_kind）
- **版本对照**：分开展示"最新代码版本"和"最近评测版本"，明确显示未评测更新
- **交接查询**：使用 PowerContext 的确定性 candidate pipeline + FTS 检索已保存记录，给出有原生 SourceRef 链路引用的交接摘要
- **技术证明面板**：显示 PowerContext 操作的实际返回结果，包括 scope/source/entry/memory 标识
- **演示数据**：支持载入完全虚构的样例团队资料（幂等导入）

## 技术栈

- **后端**：Python 3.12（已验证 3.12.3）, FastAPI
- **前端**：静态 HTML/CSS/JavaScript（无构建依赖）
- **核心依赖**：PowerContext SDK（builtin runtime + SQLite backend）
- **数据库**：SQLite（通过 PowerContext 管理）

## 安装步骤

### 1. 环境准备

确保已安装：
- Python 3.12 和 Git

### 2. 安装依赖

```bash
git clone --branch 2026-competition-ecosystem --single-branch https://github.com/Client-Qv0/cpt-powercontext.git
cd cpt-powercontext/qoder
python3.12 -m venv .venv
source .venv/bin/activate

# 安装所有依赖（包含 PowerContext SDK）
python -m pip install -r backend/requirements.txt
```

PowerContext SDK 通过 requirements.txt 固定到公开 Git revision 安装：

```
powercontext[builtin] @ git+https://github.com/Client-Qv0/cpt-powercontext.git@6d56d1ae5a0f944e04f70233d04f2b8c010b1f7b
```

- 官方上游：https://github.com/oceanbase/powercontext
- 本作品固定安装来源：https://github.com/Client-Qv0/cpt-powercontext
- 许可证: Apache 2.0
- Copyright 2026 OceanBase

### 3. 配置环境变量（可选）

```bash
# 设置数据目录（默认为 ./data）
export RELAYDESK_DATA_DIR=/path/to/data
```

## 启动步骤

### 启动后端服务

```bash
python run_server.py
```

或使用 uvicorn 直接启动：

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

服务启动后访问：
- **应用界面**：http://127.0.0.1:8000/
- **API 文档**：http://127.0.0.1:8000/docs

### 使用应用

1. **创建项目**：点击"新建项目"按钮
2. **载入演示数据**：点击侧栏的"载入演示数据"按钮（可选，所有数据均为虚构样例）
3. **记录进展**：在"进展时间线"页面添加新的进展记录，选择记录类型（进展/代码版本/评测）
4. **查询交接**：在"交接查询"页面输入问题，获取有来源引用的上下文
5. **查看版本**：在"版本对照"页面查看代码版本和评测版本状态
6. **技术证明**：在"技术证明"页面查看 PowerContext 操作的实际证据

## 验证步骤

### 运行独立验收测试

```bash
# 使用 pytest 运行独立验收测试
python -m pytest -q tests/test_independent_acceptance.py
```

测试验证：
- 查询引用匹配的原始记录及原生 SourceRef 链路
- 不匹配查询不引用无关最近进展
- 项目隔离（包括来源隔离）
- 演示数据幂等性（包括重启后）
- 正文查询和引用在重启后仍然有效
- 补录旧版评测不会倒退最新代码指针
- 新代码无评测时正确标记
- 同 commit 不同分支不算同一评测
- 时间戳带显式时区
- HTTP 空输入和不存在项目返回 422/404
- HTTP 原生引用和静态资源可访问
- 运行时发生故障时明确返回 503，不伪装为空结果

### 手动验证流程

1. **启动服务**
   ```bash
   python run_server.py
   ```

2. **创建项目**
   - 访问 http://127.0.0.1:8000/
   - 点击"+ 新建项目"
   - 输入项目名称和描述
   - 点击"创建"

3. **载入演示数据**
   - 点击侧栏"载入演示数据"按钮
   - 确认数据已加载（所有数据标注为虚构样例）

4. **查看进展**
   - 切换到"进展时间线"页面
   - 选择“示例团队项目”（演示导入会独立创建该项目）
   - 查看演示进展记录（含记录类型标签）

5. **查询交接**
   - 切换到"交接查询"页面
   - 选择项目
   - 输入问题："用户认证"
   - 查看返回的上下文、来源引用和 prepared context

6. **验证持久化**
   - 停止服务（Ctrl+C）
   - 重新启动服务
   - 刷新页面
   - 确认项目和进展记录仍然存在

7. **验证项目隔离**
   - 创建第二个项目
   - 在第二个项目中添加进展
   - 查询第一个项目，确认不会看到第二个项目的数据

8. **验证版本状态**
   - 在"版本对照"页面查看状态描述
   - 确认"最新代码版本"和"最近评测版本"分开显示
   - 确认补录旧版评测不会倒退代码指针

## API 接口

### 项目管理

- `GET /api/projects` - 列出所有项目
- `POST /api/projects` - 创建新项目
- `GET /api/projects/{project_id}` - 获取项目详情

### 进展记录

- `GET /api/projects/{project_id}/progress` - 列出项目进展
- `POST /api/progress` - 创建新进展记录（支持 record_kind: progress/code/evaluation）

### 交接查询

- `POST /api/handoff/query` - 查询交接上下文

### 版本状态

- `GET /api/projects/{project_id}/versions` - 获取版本对照状态

### 演示数据

- `POST /api/demo/load` - 载入演示数据

## PowerContext 集成说明

### 核心概念映射

| RelayDesk 概念 | PowerContext 概念 | 说明 |
|---------------|------------------|------|
| 项目 | Scope | 每个项目对应一个独立的 Scope，实现数据隔离 |
| 进展记录 | Source | 每条进展记录作为 durable ContentSource 存储 |
| 记忆 | Memory | 通过确定性 candidate_pipeline + flush() 生成，保留原生 SourceRef 链路 |
| 交接上下文 | Context | 使用 Context Preparation 提供有来源引用的查询结果 |
| 来源引用 | SourceRef | 查询结果包含实际的 source_ref 和 memory_ref |

### 确定性来源整理工作流

本应用使用 PowerContext 的**确定性 candidate_pipeline** 工作流，不使用外部 LLM：

1. **自定义 ProgressContentPipeline**：实现 `extract(request)` 方法，对 `metadata.type='progress'` 的 ContentSource 返回 `MemoryEntryInput(kind='fact', text=..., sources=(source,))`
2. **capture + flush**：调用 `runtime.sources.for_scope(scope_id).capture()` 捕获来源，然后调用 `runtime.memory.for_scope(scope_id).flush()` 处理来源到记忆
3. **原生 SourceRef 链路**：flush 后，`runtime.records.for_scope(scope_id).current_memory_entry(artifact_id, entry_id).sources` 包含实际捕获的 SourceRef
4. **追溯原文**：通过 `get_source(ref.source_type, ref.source_id)` 获取对应原文
5. **FTS 检索**：使用 `runtime.memory.for_scope(scope_id).search(SearchMemoryRequest(query=..., mode="fts"))` 进行全文搜索

### 使用的 PowerContext API

```python
# 初始化 runtime（带自定义 candidate_pipeline）
pipeline = ProgressContentPipeline()
runtime_ctx = open_builtin_runtime(config, candidate_pipeline=pipeline)
runtime = await runtime_ctx.__aenter__()

# Scope 管理
runtime.scopes.create(ScopeDraft(title=..., summary=..., idempotency_key=...))
runtime.scopes.list()

# Source 捕获
runtime.sources.for_scope(scope_id).capture(
    CaptureSource(source_id=..., content=..., metadata={"type": "progress", ...})
)

# Memory flush（触发 candidate_pipeline 处理）
await runtime.memory.for_scope(scope_id).flush()

# Memory 搜索（FTS）
runtime.memory.for_scope(scope_id).search(
    SearchMemoryRequest(query=..., mode="fts", limit=10)
)

# Context 准备
runtime.context.for_scope(scope_id).prepare(
    PrepareContextRequest(query=...)
)

# Records 查询（追溯来源）
runtime.records.for_scope(scope_id).current_memory_entry(artifact_id, entry_id)
runtime.records.for_scope(scope_id).get_source(source_type, source_id)
runtime.records.for_scope(scope_id).list_sources(limit=100, cursor=None)
```

### 不使用外部 LLM

本应用使用 PowerContext 的**确定性 candidate_pipeline** 功能，不需要配置外部推理服务或 LLM API Key。所有记忆存储和检索都通过 PowerContext 的 builtin runtime 完成。

## 数据结构

### 项目（Project）

```json
{
  "project_id": "proj-xxxxxxxxxxxx",
  "scope_id": "scp_xxxxxxxxxxxxxxxxxxxxxxxxx",
  "name": "项目名称",
  "description": "项目描述",
  "created_at": "2026-10-27T00:00:00+00:00"
}
```

### 进展记录（Progress）

```json
{
  "progress_id": "prog-xxxxxxxxxxxx",
  "project_id": "proj-xxxxxxxxxxxx",
  "record_kind": "progress|code|evaluation",
  "title": "进展标题",
  "body": "进展详情",
  "owner": "负责人",
  "status": "进行中|已完成|待处理|已阻塞",
  "next_steps": "下一步计划",
  "branch": "代码分支",
  "commit": "commit hash",
  "evaluation_result": "评测结果",
  "recorded_at": "2026-10-27T00:00:00+00:00",
  "source_ref": {
    "source_type": "content",
    "source_id": "prog-xxxxxxxxxxxx"
  }
}
```

### 交接查询结果（Handoff Query Result）

```json
{
  "project_id": "proj-xxxxxxxxxxxx",
  "question": "查询问题",
  "context_items": [
    {
      "content": "记忆文本",
      "entry_id": "entry_xxx",
      "memory_ref": {
        "artifact_id": "art_xxx",
        "revision": 1
      },
      "score": 0.85
    }
  ],
  "sources": [
    {
      "type": "progress",
      "title": "来源标题",
      "body": "来源正文",
      "progress_id": "prog-xxxxxxxxxxxx",
      "source_ref": {
        "source_type": "content",
        "source_id": "prog-xxxxxxxxxxxx"
      },
      "memory_ref": {
        "family": "memory",
        "artifact_id": "memory",
        "revision": 1
      },
      "entry_id": "entry_xxx",
      "entry_version_id": "ev_xxx"
    }
  ],
  "recent_progress": [],
  "prepared_context": {
    "status": "ready|empty",
    "content": "prepared context content",
    "note": "此上下文由 PowerContext prepare 生成，非模型推理结果"
  },
  "summary": "摘要",
  "timestamp": "2026-10-27T00:00:00+00:00"
}
```

## 安全说明

- **无认证**：本应用为本地开发工具，不包含密码、令牌或真实个人资料
- **本地监听**：服务默认只监听 127.0.0.1，不暴露到网络
- **CORS 限制**：仅允许 localhost 来源
- **输入转义**：前端使用 textContent 和 escapeHtml() 防止 XSS
- **数据隔离**：通过 PowerContext Scope 实现项目间数据隔离

## 已知限制

1. **无自动提测**：应用不会自动将代码版本标记为已评测，需要手动记录评测结果
2. **无外部 LLM**：使用确定性 candidate_pipeline，不使用外部推理服务
3. **单用户**：不支持多用户并发访问
4. **本地存储**：数据仅存储在本地 SQLite 数据库

## 故障排除

### PowerContext 导入失败

```bash
# 确保已安装依赖
python -m pip install -r backend/requirements.txt

# 验证导入
python -c "from powercontext.builtin.runtime import open_builtin_runtime; print('OK')"
```

### 数据库锁定

```bash
# 停止占用同一数据目录的本应用实例，保留数据库，再启动一个实例。
python run_server.py
```

### 端口占用

```bash
# 使用其他端口
uvicorn backend.main:app --host 127.0.0.1 --port 8001
```

## 开发说明

### 项目结构

```
qoder/
├── backend/
│   ├── __init__.py
│   ├── main.py              # FastAPI 应用
│   ├── powercontext_service.py  # PowerContext 服务层
│   └── requirements.txt     # 依赖列表（含 SDK pin）
├── static/
│   ├── index.html          # 前端页面
│   ├── style.css           # 样式
│   └── app.js              # 前端逻辑
├── tests/
│   └── test_independent_acceptance.py  # 12 项独立验收测试
├── site/
│   ├── index.html          # 展示站点
│   └── images/             # 截图目录
├── data/                   # 数据目录（自动创建）
├── run_server.py           # 启动脚本
└── README.md               # 本文档
```

### 运行测试

```bash
# 独立验收测试（推荐）
python -m pytest -q tests/test_independent_acceptance.py

# 临时诊断脚本已归档，以上 12 项是本作品提交的验收测试。
```

## 许可证

本项目使用 Apache 2.0 许可证。

PowerContext SDK Copyright 2026 OceanBase. Licensed under Apache 2.0.

## 参考

- [PowerContext SDK 源码](https://github.com/Client-Qv0/cpt-powercontext)
- [本作品源码](https://github.com/Client-Qv0/cpt-powercontext/tree/2026-competition-ecosystem/qoder)
- [FastAPI 文档](https://fastapi.tiangolo.com/)

## 联系方式

如有问题或建议，请通过项目仓库提交 Issue。

## 实测与开发记录

已在独立 Python 3.12.3 环境从公开 Git revision 安装 SDK，12 项独立验收测试通过。测试不等于赛事得分。

应用主要代码由 Qoder CLI CN 1.1.79 的真实开发会话生成；Codex 负责需求、独立验收和部分 QA 修正。详见 DEVELOPMENT.md。展示站只提供作品介绍、真实运行截图和本地复现入口；不把静态截图宣称为在线应用。

Windows 使用 Python 3.12 时可运行 python -m venv .venv，再用 .venv/Scripts/python.exe -m pip install -r backend/requirements.txt 与 .venv/Scripts/python.exe run_server.py，无需修改执行策略。
