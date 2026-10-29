# 验证环境与证据说明

本目录记录「喵喵法庭」在一台真实机器上的运行结果，方便评审核对，而不是替代评审自己的复现。

## 环境

| 项 | 值 |
| --- | --- |
| Dify | 社区版 1.18.0（官方 docker compose，`VECTOR_STORE=weaviate`、`DB_TYPE=postgresql`） |
| 模型 | DeepSeek 插件 `langgenius/deepseek` 0.0.26，模型 **`deepseek-flash`**（真实调用，非模拟） |
| PowerContext | 1.4.1（`uv tool install "powercontext[cli,server]"`，默认 SQLite） |
| 操作系统 | Windows 11 + WSL2（Ubuntu 24.04），Docker Engine 运行在 WSL 内 |

## 文件

| 文件 | 怎么来的 | 说明 |
| --- | --- | --- |
| `dify-import-final.json` | 控制台 API `POST /console/api/apps/imports` 导入 `dsl/meow-court.yml` | 证明交付的 DSL 能被 Dify 1.18.0 接受：`status=completed-with-warnings`，`error`、`warnings` 均为空 |
| `service-api-runs.json` | 应用发布后调用 `POST /v1/chat-messages`（`conversation_id` 传空 = 新会话） | 5 次真实请求的 query / user / conversation_id / message_id / 完整回复 |
| `dify-runs.md` | 由 `service-api-runs.json` 整理 | 按样例顺序排好的运行记录，便于对照 `samples/` |
| `powercontext-calls.jsonl` | `python scripts/verify_wiring.py --evidence ...` | 与 DSL 四个 HTTP 节点完全一致的请求体、状态码与响应片段（真实往返） |
| `screenshots/` | Playwright 驱动真实 Chrome 登录 Dify 后截图 | 7 张界面截图，见下表 |

## 界面截图

| 文件 | 内容 |
| --- | --- |
| `screenshots/01-apps.png` | Dify 工作室里的「喵喵法庭」（CHATFLOW） |
| `screenshots/02-workflow.png` | Chatflow 画布：15 个节点、两条分支（审判 / 查卷宗） |
| `screenshots/03-logs.png` | 运行历史：4 次常规运行，全部绿色 `SUCCESS`，玩家 `real-a` / `real-b` |
| `screenshots/04-log-detail.png` | 第 2 号那次运行的对话：★★☆☆☆、前科 1 次、`援引旧案：第 1 号`、末尾 `art_...` 归档回执 |
| `screenshots/05-chat-dossier.png` | 「查卷宗」分支：直接列出 PowerContext 里的两条案底（不调用模型） |
| `screenshots/06-chat-verdict.png` | 第 1 号那次运行的完整判决书与归档回执 |
| `screenshots/07-offline-fallback.png` | 离线兜底：PowerContext 停止时输出「⚠️ 卷宗柜打不开」+ 排查指引 |

`03-logs.png` 是在前 4 次运行之后拍的，所以列表里只有 4 条、全是 `SUCCESS`。第 5 条
（`07-offline-fallback.png` 里那条 `PARTIAL SUCCESS`）是**故意**在 PowerContext 停止时发起的降级测试：
它走的是设计内的兜底分支，因此状态不是 `SUCCESS`，页面上也不会出现 `FAILURE`。

截图里的判词均由 DeepSeek 真实生成，案号与星级就是当时卷宗的状态；`04` 里的「第 2 号」与 `06` 里的
「第 1 号」正好证明第二次判决引用了第一次。

## 五次运行分别验证什么

全部使用交付的 `dsl/meow-court.yml`，没有替换任何节点。

| 记录 | 玩家 | 输入 | 验证点 |
| --- | --- | --- | --- |
| A-首次开庭 | `real-a` | 「我把猫罐头换成了减肥罐头，还说是猫自己说要减肥」 | 判词第 1 号、★☆☆☆☆、判词不引用不存在的旧案、归档回执给出真实 `artifact_id` |
| B-新会话累犯 | `real-a` | 「我昨晚三点把你从键盘上抱走了」（新会话） | 案号升到第 2 号、累犯 ★★、前科 1 次、判词**主动援引第 1 号**并复述其罪名 |
| C-查卷宗 | `real-a` | 「查卷宗」 | 条件分支走确定性路径（不调用模型），直接列出 2 条案底 |
| D-另一位铲屎官首次开庭 | `real-b` | 「我把你的纸箱扔了，还说是风干的」 | 换 `user` 即换卷宗：另一位玩家从第 1 号、★☆☆☆☆ 开始 |
| E-离线兜底 | `real-c` | 「我把你的猫粮偷吃了」（此时 PowerContext 已停止） | 输出「⚠️ 卷宗柜打不开」+ 排查指引，而不是报错页 |

## 关于 `tests/meow-court.stub-llm.yml`

这个副本把 LLM 节点换成确定性 Code 桩，用于**完全没有模型额度**的机器做接线演示：

```bash
python tests/make_stub_variant.py dsl/meow-court.yml tests/meow-court.stub-llm.yml
```

本目录的证据**不是**用它跑出来的——上面 5 次都是真实模型调用。

## 复现这些证据

```bash
# 1. 起 PowerContext
powercontext server run --host 127.0.0.1 --port 8000

# 2. 接线自检 + 真实调用日志（不需要 Dify、不需要模型）
python -m pip install pyyaml
python scripts/verify_wiring.py --user grader-demo \
  --turn "我把猫罐头换成了减肥罐头" --turn "查卷宗" \
  --stub-verdict samples/offline-verdict.json \
  --evidence evidence/powercontext-calls.jsonl

# 3. Dify 侧：导入 DSL → 绑定模型 → 发布 → 用 Service API 或 Web 界面按 samples/ 逐步体验
curl -s -X POST 'http://<dify>/v1/chat-messages' \
  -H 'Authorization: Bearer <app-API-key>' -H 'Content-Type: application/json' \
  -d '{"inputs":{},"query":"查卷宗","response_mode":"blocking","user":"real-a","conversation_id":""}'
```
