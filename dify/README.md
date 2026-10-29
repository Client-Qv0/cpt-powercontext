# 喵喵法庭 · Meow Court

> 一只记仇的橘猫法官，用 **PowerContext** 把你的每一件小事记进卷宗，并在下一次开庭时逐条翻出来。

Dify Chatflow × PowerContext 记忆读写 · 2026 OceanBase 数据库大赛「Dify × OceanBase / Just for Fun」参赛作品

---

## 1. 这是什么

你被传唤到「喵喵法庭」，主审法官是一只橘猫**橘座**。你在猫面前干过的每件小事——换掉猫罐头、半夜把它从键盘上抱走、把它的纸箱扔了还说是风干的——都会被写进它的卷宗。

好玩的地方在于：**卷宗不会随着聊天窗口关闭而消失**。

- 第 1 次开庭：你是初犯，法官不屑地罚你三块鸡胸肉。
- 关掉窗口、重新开一个会话：法官开口就是「第 2 号案件」，并引用你上次的供词来判断这次是不是**狡辩**。
- 犯罪记录累积到 4 星，法官会在判词里追加【通缉令】；到 5 星，它开始怀疑你整个人。
- 输入「查卷宗」，法官不用模型、直接把 PowerContext 里的原始条目念给你听——这就是「它真的记得」的证据。

这是一个**纯文本、即开即玩**的作品：不需要额外前端，Dify 提供的 Web 应用界面就是入口。

### 1.1 三步就能玩

1. 打开应用，看到开场白（法庭宣告）。
2. 直接说你干了什么，比如「我把猫罐头换成了减肥罐头，还说是猫自己说要减肥」。
3. 收到一份带**案号、案由、判词、刑罚、援引旧案**的判决书，末尾一行回执会告诉你这次判决被归档到 PowerContext 的哪一条记忆里。

想看它到底记得多少：输入「查卷宗」。

### 1.2 规则（给评审的预期说明）

| 玩家输入 | 走哪条路 | 预期表现 |
| --- | --- | --- |
| 一段「罪行」自述（任意自由文本） | 审判分支 | LLM 法官生成严格 JSON 判词 → 渲染成判决书 → 写回 PowerContext |
| 含「卷宗 / 案底 / 查卷 / 前科 / 档案 / 记录」的字样 | 程序分支 | 不发模型请求，直接输出 PowerContext 里的原始案底清单 |
| PowerContext 连不上 | 程序分支 | 输出可诊断的「卷宗柜打不开」提示，而不是空白报错 |

判决内容由模型生成，**没有唯一标准答案**；可核对的是：案号递增、累犯星级随前科数量变化、判词是否援引旧案编号、归档回执里的条目编号是否真实。

---

## 2. 技术分工

本作品使用 **Dify + PowerContext**（题目允许 seekdb / PowerContext 二选一，本作品选了 PowerContext，未使用 seekdb）。

| 组成 | 在本作品里实际承担什么 | 对应材料 |
| --- | --- | --- |
| **Dify**（必选） | Chatflow 共 15 个节点承担全部编排：输入归一化 → 取/建卷宗柜 → 调阅案底 → 计数与分级 → **条件分支** → 模型判决 → 判词解析 → 归档 → 输出。四个 HTTP Request 节点负责与 PowerContext 通信，两个 Answer 节点分别输出「判决书」和「卷宗」 | `dsl/meow-court.yml` |
| **PowerContext** | 承担**跨会话记忆**的全部职责：`Scope` = 一位玩家的卷宗柜；`memory/remember` = 归档判决；`memory/entries/list` = 通读案底并算前科；`context/prepare` = 按本次罪行组装带引用、有字节预算的前科摘录，直接喂给模型 | 同上 DSL 的四个 HTTP 节点 + 第 6 节证据 |

没有「记在聊天窗口里」的取巧做法：Dify 的会话变量在新建会话时会被清空，所有跨会话信息**只能**从 PowerContext 取回。这也是本作品选择 PowerContext 的理由——它天生就在解决「换个会话还记得」。

### 2.1 节点清单（与 DSL 一一对应）

| # | 节点 id | 类型 | 作用 |
| --- | --- | --- | --- |
| 1 | `start` | start | 接收玩家发言（即「罪行陈述」） |
| 2 | `intake` | code | 归一化玩家标识（`sys.user_id` → Scope 安全字符）、识别「查卷宗」意图、截断超长输入 |
| 3 | `scope` | http-request | `POST /v1/scopes`，用幂等键取回或创建该玩家的卷宗柜 |
| 4 | `parsed_scope` | code | 解析 `scope_id`；解析失败标记 `scope_ok=no` |
| 5 | `dossier` | http-request | `POST /v1/memory/entries/list`，取回该 Scope 全部记忆条目 |
| 6 | `brief` | code | 数前科、算累犯星级（1–5★）、算保释金、生成卷宗清单与提示词摘要 |
| 7 | `routing` | if-else | 意图=查卷宗 **或** 卷宗柜不可用 → 程序分支；否则 → 审判分支 |
| 8 | `answer_dossier` | answer | 程序分支：原样输出案底 |
| 9 | `precedent` | http-request | `POST /v1/context/prepare`，按本次陈述取相似前科的 Prepared Context |
| 10 | `precedent_ctx` | code | 从 PowerContext 的 `BEGIN/END_POWERCONTEXT_PREPARED_CONTEXT_V1` 信封里只取记忆正文 |
| 11 | `judge` | llm | 橘座法官：结合卷宗摘要 + 相似前科 + 累犯星级，输出严格 JSON 判词 |
| 12 | `verdict` | code | 解析 JSON；模型乱输出时降级（仍会归档），并组装判决书与归档文本 |
| 13 | `archive` | http-request | `POST /v1/memory/remember`，把本次判决写回卷宗 |
| 14 | `receipt` | code | 从归档响应里取出真实 `artifact_id`，作为「已归档」回执 |
| 15 | `answer_verdict` | answer | 输出判决书 + 回执 |

### 2.2 记忆的一条完整链路

```
玩家："我把猫罐头换成了减肥罐头"
  │
  ├─ scope      → scp_xxxx（幂等：meow-court:v1:<player>）
  ├─ dossier    → 3 条旧案                     ← 跨会话来源
  ├─ brief      → 前科 3 次 · 累犯★★★☆☆
  ├─ precedent  → 与「罐头」最相关的旧案摘录（带 citation，按字节预算组装）
  ├─ judge      → {"charge": "...", "verdict": "本庭援引第 1 号...", ...}
  ├─ archive    → art_yyyy（kind=meow-court/case）
  └─ receipt    → "本案已归档到 PowerContext 卷宗：art_yyyy"
```

---

## 3. 运行环境

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| Dify | **1.18.0**（社区版，docker compose 部署） | 本作品的 DSL 已在 1.18.0 上完成导入与逐节点运行（见 `evidence/`）；DSL 采用 `version: 0.3.1` 导出格式，导入时会被升级为当前 DSL 版本 |
| 模型 | **DeepSeek `deepseek-flash`**（默认，插件 `langgenius/deepseek` 0.0.26）；任何能按 JSON 输出的聊天模型都可以替换 | 换模型只需在 LLM 节点上重新选择，见 4.3 |
| PowerContext Server | **1.4.1**（PyPI `powercontext[cli,server]`） | 默认 SQLite 存储，无需向量库、无需 embedding 模型 |
| Python（只跑辅助脚本时需要） | 3.10+ | `scripts/` 下两个脚本，`seed` 只用标准库，`verify_wiring` 需要 `pyyaml` |
| 网络 | Dify 容器 → PowerContext Server 的 HTTP 连通 | 见 4.2 的 `host.docker.internal` 说明 |

> PowerContext 1.4.1 的显式记忆（`remember` / `entries/list` / `context/prepare`）**不需要**配置 generation / embedding 模型。启动时那句 "未配置推理模型" 的提示不影响本作品。

**已验证到什么程度**（细节见 `evidence/README.md`）：

- ✅ `dsl/meow-court.yml` 在 Dify 1.18.0 中导入成功（无 error / 无 warning）；
- ✅ 15 个节点在 Dify 中跑通：4 次 PowerContext 调用、条件分支、判词解析、归档回执全部成功（经 Service API 的 5 次真实对话验证）；
- ✅ 跨会话：换新会话后案号与累犯等级按记忆递增；
- ✅ 兜底：PowerContext 停掉时输出可读提示而非报错；
- ✅ **用真实模型跑通**：DeepSeek `deepseek-flash` 按提示词输出严格 JSON，判词、累犯升级、援引旧案、归档回执全部正常（见 `evidence/dify-runs.md`）。

---

## 4. 从零跑起来

### 4.1 启动 PowerContext Server

```bash
# 方式 A：从 PyPI 装固定版本（本作品验证用的就是 1.4.1）
uv pip install "powercontext[cli,server]==1.4.1"
powercontext server run --host 127.0.0.1 --port 8000

# 方式 B：从 GitHub 装（与官方 API 快速开始一致；master 会随时间变化）
uv tool install --force "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@master"
powercontext server run --host 127.0.0.1 --port 8000
```

PowerContext 侧没有其他 Python 依赖、也不需要向量库或 embedding 服务；`1.4.1` 与 `1.4.x` 的这四个接口都兼容。

另一个终端确认：

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/health/live
# {"status":"ok"}
```

数据默认落在系统用户数据目录（Windows：`%LOCALAPPDATA%\powercontext`，Linux：`~/.local/share/powercontext`）。想固定目录就先设 `POWERCONTEXT_HOME`：

```powershell
$env:POWERCONTEXT_HOME = "D:\powercontext-data"
powercontext server run --host 127.0.0.1 --port 8000
```

### 4.2 让 Dify 的容器能访问 PowerContext

DSL 里已经把这个地址做成**环境变量 `POWERCONTEXT_BASE_URL`**（默认 `http://host.docker.internal:8000`），四个 HTTP 节点都引用它。

- **Docker Desktop（Windows / macOS）**：`host.docker.internal` 直接可用，保持默认即可。
- **Linux / WSL2 里的 Docker Engine**：需要给容器补一条 host 映射。**注意要同时给 `ssrf_proxy` 加**，因为 Dify 的 HTTP 节点是经 SSRF 代理出网的，只给 `api` 加不生效（这是本作品实际踩到的坑）：

  ```yaml
  # docker-compose.override.yaml（放在 dify/docker/ 目录，然后 docker compose up -d）
  services:
    api:
      extra_hosts: ["host.docker.internal:host-gateway"]
    worker:
      extra_hosts: ["host.docker.internal:host-gateway"]
    ssrf_proxy:
      extra_hosts: ["host.docker.internal:host-gateway"]
  ```

- **允许访问内网地址**：Dify 默认禁止 HTTP 节点访问私有网段，返回 `503`（响应体是 Squid 的错误页）。在 `dify/docker/.env` 里放开你要用的网段，然后 `docker compose up -d api worker ssrf_proxy`：

  ```bash
  # 逗号分隔的 CIDR，不是 true/false（写成 true 会让 ssrf_proxy 起不来）
  SSRF_PROXY_ALLOW_PRIVATE_IPS=172.16.0.0/12,10.0.0.0/8,192.168.0.0/16
  ```

- **PowerContext 跑在另一台机器**：把环境变量改成 `http://<host>:8000`，并让 Server 监听 `0.0.0.0`。非回环监听需要显式确认：

  ```bash
  POWERCONTEXT_SERVER_ALLOW_UNAUTHENTICATED_NON_LOOPBACK=true \
    powercontext server run --host 0.0.0.0 --port 8000
  ```

  （这是「本机演示可用的裸奔模式」，生产环境请改用 Bearer token 鉴权。）

> 容器里**不能**写 `http://127.0.0.1:8000`——那是容器自己。

**一分钟自检**（在 Dify 的 api 容器里跑）：

```bash
docker compose exec api curl -s http://host.docker.internal:8000/health/live
# 期望：{"status":"ok"}
```

### 4.3 在 Dify 里导入 DSL

1. Dify 控制台 → 应用 → **导入 DSL 文件** → 选择 `dsl/meow-court.yml`。
2. 打开导入后的「喵喵法庭」→ 工作流编辑器里的 **环境变量**（`POWERCONTEXT_BASE_URL`），把值改成你能访问的地址（4.2）。默认是 `http://host.docker.internal:8000`。
3. 打开 **`橘座法官`（LLM 节点）**，在模型下拉里选择你已配置好的模型：
   - 默认写的是 DeepSeek `deepseek-flash`（provider `langgenius/deepseek/deepseek`）。Dify 1.x 的模型供应商是插件，需要先在「插件 → 探索 Marketplace」里安装 **DeepSeek** 插件（本机实测 0.0.26）并填入 API Key。
   - 如果你的 DeepSeek 插件里没有 `deepseek-flash`（老版本插件只有 `deepseek-chat` / `deepseek-reasoner`），在下拉里选一个可用模型即可，DSL 其余部分不用改。
   - 用别的模型（OpenAI / 通义 / 本地 Ollama / OpenAI-API-compatible）：**只改这一个节点的模型选择**，其余节点、提示词、变量都不用动。
   - 提示词要求模型输出**严格 JSON**；建议温度 ≥ 0.8（默认 0.9），`max_tokens` 1200。
4. 点「发布」→ 用「运行」或在「访问 API / WebApp」里体验。

DSL 里没有知识库、没有插件依赖（`dependencies: []`），唯一的运行依赖是 PowerContext Server 和你的模型。

### 4.4（可选）预置前科，让累犯玩法一开局就成立

```bash
python scripts/seed_demo_memory.py --base-url http://127.0.0.1:8000 --user demo-grader
```

它会用**与工作流完全相同的 Scope 幂等键和记忆格式**写入 3 条前科（第 1–3 号），所以预置数据和后续真实判决会在同一个卷宗里。重复执行不会重复写入（要重复写加 `--force`）。

---

## 5. 验证样例

三组样例覆盖了「主要玩法」「跨会话记忆」「失败兜底」。每组都给了初始状态、输入、预期表现和恢复方式。

> 详细逐字记录见 `samples/`，真实调用日志见 `evidence/`。

### 样例 A · 首次开庭（无前科）

- **初始状态**：该玩家没有任何记忆条目（新 `user`，或刚清空卷宗）。
- **输入**：`我把猫罐头换成了减肥罐头，还说是猫自己说要减肥`
- **预期表现**：
  - 判词开头是「第 1 号」；
  - 累犯等级 `★☆☆☆☆（前科 0 次）`；
  - 判词中出现「本庭第一次见你」之类的表述（模型措辞可变）；
  - 末尾回执含 `本案已归档到 PowerContext 卷宗：art_...`。
- **怎么核对**：复制回执里的 `artifact_id`，然后

  ```bash
  curl -s -X POST http://127.0.0.1:8000/v1/memory/entries/list \
    -H 'Content-Type: application/json' \
    -d '{"scope_id":"<你的 scope_id>"}'
  ```

  能看到这条记忆的 `kind` 是 `meow-court/case`。

### 样例 B · 跨会话累犯（本作品的核心样例）

- **初始状态**：样例 A 已执行（卷宗里有 1 条）。
- **操作**：**关掉当前会话，新建一个会话**（重要：确认新会话里没有旧上下文），输入
  `我昨晚三点把你从键盘上抱走了`
- **预期表现**：
  - 案号变成「第 2 号」，累犯等级 `★★☆☆☆（前科 1 次）`；
  - 判词**必须**援引第 1 号旧案，并说明它和这次的关系；
  - 回执给了新的 `artifact_id`。
- **为什么这能证明记忆来自 PowerContext**：新会话里 Dify 的会话变量已清空，案号与前科次数只能来自 `memory/entries/list`。
- **恢复初始状态**：换一个 `user` 重新开始（见 6.4），或用样例 A 的账号继续累加。

### 样例 C · 查卷宗（不消耗模型额度）

- **输入**：`查卷宗`
- **预期表现**：直接输出一份卷宗清单（「### 📜 卷宗 · 共 N 号」+ 每条案底），**不会**出现判决书格式，也不会调用模型。
- **用途**：模型额度没配好时也能验收 PowerContext 接线是否正常；评委可以拿这里的条目和 `entries/list` 的返回逐条对照。

### 失败兜底

- **输入**：任意罪行，但先停掉 PowerContext Server（或把 `POWERCONTEXT_BASE_URL` 改成错误端口）。
- **预期表现**：不出现 500 空白页，而是「⚠️ 卷宗柜打不开」+ 指向 README 4.2 的排查提示。

---

## 6. PowerContext 到底做了什么（技术证据）

### 6.1 四个真实调用

| 时机 | 请求 | 为什么必须用它 |
| --- | --- | --- |
| 每次发言 | `POST /v1/scopes`<br>`{title, summary, idempotency_key: "meow-court:v1:<player>"}` | 把「一位玩家」映射成「一个 Scope」。幂等键保证同一玩家永远落回同一个卷宗柜，不会因为新建会话而分裂成多个 |
| 每次发言 | `POST /v1/memory/entries/list`<br>`{scope_id}` | 取回**全部**历史判决，用条数算前科次数与累犯星级。这是「跨会话」的唯一来源 |
| 审判分支 | `POST /v1/context/prepare`<br>`{scope_id, query: <本次罪行>}` | 让 PowerContext 按本次陈述检索并组装**带 citation、有字节预算**的前科摘录，比把所有案底塞进提示词更聚焦，也避免提示词无限膨胀 |
| 判决之后 | `POST /v1/memory/remember`<br>`{scope_id, kind: "meow-court/case", text, reason}` | 归档本次判决。`text` 里带案号、累犯星级、自述、案由、判词、刑罚、援引旧案，下一次开庭可直接复用 |

### 6.2 可以直接看的证据

1. **对话里的回执**：每条判决书末尾都有 `本案已归档到 PowerContext 卷宗：art_...`。这是 `memory/remember` 响应里 `records[0].artifact.artifact_id` 的原值，不是编的。
2. **卷宗分支**：输入「查卷宗」得到的清单，与 `memory/entries/list` 的返回逐条一致。
3. **调用日志**：`evidence/powercontext-calls.jsonl` 记录了每个 HTTP 节点的真实请求体、状态码和响应片段（由 `scripts/verify_wiring.py --evidence` 生成，节点、请求体、URL 与 DSL 完全一致）。
4. **Dify 侧记录**：`evidence/dify-runs.md` 是经应用自己的 Service API（`POST /v1/chat-messages`）跑出来的 5 次真实对话，原始返回在 `evidence/service-api-runs.json`；每次运行的逐节点请求与响应可在 Dify 的「日志与标注 → 运行历史」里核对。

### 6.2.1 本仓库附带哪些实测记录

| 材料 | 验证了什么 |
| --- | --- |
| `evidence/dify-import-final.json` | 交付的 `dsl/meow-court.yml` 在 **Dify 1.18.0** 里导入成功（`error`、`warnings` 均为空） |
| `evidence/service-api-runs.json` | 5 次经 Service API 的真实对话：首次开庭、新会话累犯、查卷宗、新玩家空卷宗、离线兜底 |
| `evidence/dify-runs.md` | 上面 5 次的完整回复与核对要点，按样例顺序排列 |
| `evidence/powercontext-calls.jsonl` | 四个 HTTP 调用的真实请求/响应（含 scope_id、条目正文） |

上面 5 次运行使用的就是交付的 `dsl/meow-court.yml`，模型是真实的 DeepSeek `deepseek-flash`，没有替换任何节点。判词里的语气与措辞由模型生成，每次不同；可复核的是案号、累犯星级、前科条数、援引旧案编号、分支走向与 `artifact_id`。详见 `evidence/README.md`。


### 6.3 数据格式（便于核对）

一条卷宗记忆的 `text` 长这样：

```
第3号 · 累犯★★★☆☆ · 被告自述：把猫的纸箱扔了，还说是风干的 | 案由：毁坏猫居 |
判读：嫁祸天气 | 判决：本庭援引第 2 号，被告已构成惯犯，本次启用通缉令 |
刑罚：罚新纸箱两个 | 附加条款：通缉令张贴于冰箱门 | 援引旧案：第 2 号
```

`kind` 固定为 `meow-court/case`，所以即使同一 Scope 里混进别的记忆，前科计数也不会被污染。

### 6.4 玩家标识（Scope）怎么对应

- 工作流用 Dify 系统变量 `sys.user_id` 作为玩家标识，经 `intake` 节点清洗成 `[0-9A-Za-z_-]{1,40}`，再拼成幂等键 `meow-court:v1:<key>`。
- **Web 界面**：`sys.user_id` 由浏览器会话决定——**同一个浏览器 = 同一个铲屎官**，所以「关掉会话再开一个」就能看到跨会话效果。
- **API 体验**（推荐给评审复现）：

  ```bash
  curl -X POST 'http://<dify>/v1/chat-messages' \
    -H 'Authorization: Bearer <app-API-key>' \
    -H 'Content-Type: application/json' \
    -d '{"inputs":{},"query":"查卷宗","response_mode":"blocking","user":"demo-grader","conversation_id":""}'
  ```

  换成 `"user":"demo-grader-2"` 就是一个全新的玩家（空卷宗），可以反复验证「首次开庭」。
- 想彻底清空一位玩家的案底：换一个 `user`，或用 Dify 侧新的无痕浏览器（等价于新 `sys.user_id`）。

---

## 7. 文件清单

```
dify/
├── dsl/
│   └── meow-court.yml              # 主应用 DSL（导入这一个文件即可）
├── scripts/
│   ├── seed_demo_memory.py         # 预置前科（幂等；只用标准库）
│   ├── reset_player.py             # 清空某位玩家的前科（软删除，前科归零）
│   └── verify_wiring.py            # 接线自检：不用 Dify/模型也能验证四个 HTTP 调用与节点逻辑
├── tests/
│   ├── make_stub_variant.py        # 可选：由主 DSL 生成「LLM 换成确定性桩」的副本
│   └── meow-court.stub-llm.yml     # 可选：完全没有模型额度时的接线演示副本
├── samples/
│   ├── sample-a-first-hearing.md   # 首次开庭
│   ├── sample-b-cross-session.md   # 跨会话累犯（核心）
│   ├── sample-c-dossier.md         # 查卷宗（不花模型额度）
│   └── offline-verdict.json        # 离线自检用的判词桩（不是模型输出）
└── evidence/
    ├── README.md                   # 验证环境与证据说明
    ├── dify-import-final.json      # DSL 在 Dify 1.18.0 的导入结果
    ├── service-api-runs.json       # 5 次真实对话的原始返回
    ├── dify-runs.md                # 运行记录 + 核对要点
    ├── powercontext-calls.jsonl    # 真实 PowerContext 请求/响应
    └── screenshots/                # 7 张 Dify 界面截图（应用、画布、日志、判决书、查卷宗、离线兜底）
```

`scripts/verify_wiring.py` 的定位：**接线自检**，不是第二个实现。它按 DSL 的节点顺序执行 code / http-request / if-else / answer 节点，用来在没有 Dify、没有模型额度的机器上确认「四个 PowerContext 调用真的有数据往返」（本作品的正式验证用的是真实模型，见 `evidence/`）。LLM 节点在离线模式下使用 `samples/offline-verdict.json` 里的桩数据，输出会明确标注；**正式体验与评分仍以 Dify 里运行的结果为准**。

```bash
python -m pip install pyyaml
python scripts/verify_wiring.py --user demo-grader --turn "查卷宗"
python scripts/verify_wiring.py --user demo-grader \
  --turn "我把猫罐头换成了减肥罐头" --stub-verdict samples/offline-verdict.json \
  --evidence evidence/powercontext-calls.jsonl
```

---

## 8. 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| 判决书位置出现「卷宗柜打不开」 | Dify 容器访问不到 PowerContext。按 4.2 检查 `POWERCONTEXT_BASE_URL`、`extra_hosts`（含 `ssrf_proxy`）与 `SSRF_PROXY_ALLOW_PRIVATE_IPS`；在容器里 `curl $POWERCONTEXT_BASE_URL/health/live` 应返回 `{"status":"ok"}` |
| HTTP 节点返回 503，响应体是一张 Squid 错误页 | 命中了 Dify 的 SSRF 代理：①`host.docker.internal` 解析不到（给 `ssrf_proxy` 加 `extra_hosts`）；②目标在私有网段但未放开（`SSRF_PROXY_ALLOW_PRIVATE_IPS=<CIDR,...>`，别写 `true`） |
| `ssrf_proxy` 容器反复重启 | `SSRF_PROXY_ALLOW_PRIVATE_IPS` 写成了 `true` 之类不是 CIDR 的值，Squid 启动失败；改成 `172.16.0.0/12` 这样的网段后 `docker compose up -d ssrf_proxy` |
| `connection refused` / `timeout` | PowerContext 没启动，或监听的 host 不对（只监听 `127.0.0.1` 时容器访问不到），用 `--host 0.0.0.0` |
| 启动时报 `PermissionError ... \powercontext` | 数据目录不可写，设置 `POWERCONTEXT_HOME` 到可写目录 |
| 模型节点报「模型不存在」/ 运行直接失败于 Provider ... does not exist | 供应商插件没装或没配 Key：到「插件 → Marketplace」安装 DeepSeek（或其他供应商）插件，填入 Key 后回到 4.3 第 3 步重新选模型并发布 |
| 判词是纯文本、没有「案由/刑罚」格式 | 模型没按 JSON 输出，`verdict` 节点走了降级路径（仍会归档）。换更强的模型或降低温度重试 |
| 累犯星级不涨 | 检查是不是换了浏览器/`user`（换人=新卷宗）；用样例 C 的「查卷宗」确认条目数 |
| 检索摘录偶尔为空 | 中文全文检索按查询词匹配，口语化短句可能命中不到；此时提示词里会写「本庭按新案审理」，判词仍会引用卷宗摘要 |
| 想清空所有案底 | PowerContext 没有「删除 Scope」的必需操作，换一个新 `user` 即可得到空卷宗 |

## 9. 已知限制

- 单机 SQLite 存储，面向单人演示；未做并发压测。
- 无鉴权：PowerContext 与 Dify 都按本机/内网演示配置。生产部署应开启 Server 的 Bearer token，并把 token 放进 Dify 的 HTTP 节点鉴权，**不要**写进提示词。
- 判决书内容由模型生成，不保证每次一致；可核对的是案号、累犯星级、是否援引旧案、归档条目编号。
- 卷宗只展示最近 12 条（判词里最多引用 6 条），更早的记录仍在 PowerContext 中，可以通过 API 取回。
- 未使用 seekdb（题目允许二选一）。

## 10. 提交材料对照

按赛题「四、提交材料」逐项对齐，评审可以直接照这张表找文件。

### 10.1 4.1 Dify DSL

| 要求 | 材料 |
| --- | --- |
| 全部 DSL 文件 | `dsl/meow-court.yml`（**只有一个文件**，导入后即为完整应用，无导入顺序要求） |
| 各文件用途 | 主应用：Chatflow 15 节点，含 4 个 PowerContext HTTP 节点、1 个 LLM 节点、2 个 Answer 节点 |
| 适用 Dify 版本与部署方式 | Dify 社区版 **1.18.0**（官方 docker compose，`VERSION` 镜像 tag 均为 1.18.0）；DSL 导出格式 `version: 0.3.1`，导入时升级到实例当前版本 |
| 重新绑定服务地址的步骤 | 工作流编辑器 → 环境变量 `POWERCONTEXT_BASE_URL`（见 4.2） |
| 重新绑定模型的步骤 | 打开 `橘座法官` 节点 → 模型下拉重新选（见 4.3） |

### 10.2 4.2 运行说明

本文即是运行说明，覆盖：玩法与分工（1–2 节）、环境与版本（3 节）、安装到启动的完整步骤（4 节）、验证样例（5 节）、外部服务与网络条件（4.2）、已知限制（9 节）。

**凭据与占位值声明**：仓库内**不含**任何 API Key、密码或 token（提交前已扫描）；README 中的 `http://host.docker.internal:8000`、`<dify>`、`<app-API-key>`、`<scope_id>` 均为占位值。真实 Key 只存在于部署者自己的 Dify 实例里。

### 10.3 4.3 验证样例与运行证据

| 要求 | 材料 |
| --- | --- |
| 初始状态 / 输入 / 操作顺序 | `samples/sample-a…c`（含「如何恢复初始状态」） |
| 预期交互与输出形式 | 同上（每节都有「预期表现」表） |
| 实际运行结果 | `evidence/dify-runs.md` + `evidence/service-api-runs.json`（5 次真实对话原文） |
| 截图 | `evidence/screenshots/`（7 张，见 10.5） |
| PowerContext 的作用与记录 | 6.1 四个调用 + `evidence/powercontext-calls.jsonl` + 对话里的 `art_...` 回执 |

### 10.4 4.4 按依赖补充的材料

| 涉及内容 | 本作品情况 |
| --- | --- |
| 使用 seekdb 部署 Dify | **不适用**。本作品选择 PowerContext（题目允许二选一），未使用 seekdb，Dify 使用官方 compose 默认 PostgreSQL |
| 知识库或外部数据 | **不适用**。不使用知识库、不依赖外部语料；演示所需的「前科」由 `scripts/seed_demo_memory.py` 幂等生成（数据为虚构示例） |
| 预置记忆或互动状态 | `scripts/seed_demo_memory.py`：写入第 1–3 号案底。用户与会话标识如何关联见 6.4（`sys.user_id` → Scope 幂等键 `meow-court:v1:<player>`） |
| 现成插件 | 见 10.5 插件清单（DeepSeek 0.0.26，Marketplace 安装） |
| 自定义插件 | **不适用**。未开发自定义插件；与 PowerContext 的通信全部由 Dify 内置的 HTTP Request + Code 节点完成 |
| 自定义后端或前端 | **不适用**。没有自建后端/前端；`scripts/` 下两个 Python 脚本只是部署期辅助工具（预置数据、接线自检），不是运行时依赖 |

### 10.5 插件与截图清单

**现成插件**

| 插件 | 版本 | 安装来源 | 配置项 | 用途 |
| --- | --- | --- | --- | --- |
| DeepSeek（`langgenius/deepseek`） | 0.0.26 | Dify 插件 Marketplace | API Key（本机为占位，不提交） | `橘座法官` 节点生成结构化判词 |

**界面截图**（`evidence/screenshots/`）

| 文件 | 内容 |
| --- | --- |
| `01-apps.png` | 工作室里的「喵喵法庭」应用 |
| `02-workflow.png` | Chatflow 画布（15 节点 + 两条分支） |
| `03-logs.png` | 运行历史：4 次常规运行，全部 `SUCCESS`（`real-a` / `real-b`） |
| `04-log-detail.png` | 第 2 号运行的对话：★★☆☆☆、援引第 1 号、归档回执 |
| `05-chat-dossier.png` | 「查卷宗」分支输出（不调用模型） |
| `06-chat-verdict.png` | 第 1 号的完整判决书 + `art_...` 归档回执 |
| `07-offline-fallback.png` | 离线兜底：PowerContext 停止时的「⚠️ 卷宗柜打不开」 |

---

## 11. 参考与致谢

- PowerContext 项目：<https://github.com/oceanbase/powercontext>
- PowerContext API 快速开始：<https://powercontext.oceanbase.io/zh/docs/develop/api-quickstart/>
- PowerContext 接口说明：<https://powercontext.oceanbase.io/zh/docs/develop/interfaces/>
- Dify HTTP Request 节点：<https://docs.dify.ai/en/cloud/use-dify/nodes/http-request>
- Dify 应用导入导出：<https://docs.dify.ai/en/cloud/use-dify/workspace/app-management>
- 玩法参考（仅参考选题形式，未复用其 DSL）：`dzh-gitcode/dify-workflows`、`wwwzhouhui/dify-for-dsl`

本作品原创：DSL 全部节点与提示词、两个辅助脚本、演示数据与验证样例。
