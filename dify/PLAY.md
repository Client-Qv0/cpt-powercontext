# 喵喵法庭 · 怎么玩

> 一句话：你被一只记仇的橘猫传唤上庭，它把你们之间的每一笔恩怨都记在 PowerContext 卷宗里；**关掉窗口重开，它照样记得**，还会翻出你上一次的案底来加刑。

这份文档只讲「怎么把它跑起来、怎么点、怎么玩」。技术实现和部署细节看 [README.md](README.md)。

---

## 0. 一分钟速查

需要**两个** WSL 终端：A 跑记忆库（PowerContext），B 跑 Dify。

**终端 A**

```bash
export POWERCONTEXT_HOME=$HOME/pcdata
export POWERCONTEXT_SERVER_ALLOW_UNAUTHENTICATED_NON_LOOPBACK=true
~/.local/bin/powercontext server run --host 0.0.0.0 --port 8000
# 看到 "Uvicorn running on http://0.0.0.0:8000" 就好了，终端停在这里是正常的
```

**终端 B**

```bash
curl -s http://127.0.0.1:8000/health/live          # {"status":"ok"}
cd ~/dify/docker && docker compose up -d
docker compose ps                                   # 关键服务 Up / healthy
docker compose exec api curl -s http://host.docker.internal:8000/health/live   # {"status":"ok"}
ip -4 addr show eth0 | grep -oP 'inet \K[\d.]+'     # 例如 172.17.58.240
```

浏览器打开 `http://<上一步的地址>/` → 登录 → 「工作室」→ 🐱 喵喵法庭 → 右上「预览」→ 开聊。

---

## 1. 终端 A：启动 PowerContext（记忆库）

```bash
export POWERCONTEXT_HOME=$HOME/pcdata
export POWERCONTEXT_SERVER_ALLOW_UNAUTHENTICATED_NON_LOOPBACK=true
~/.local/bin/powercontext server run --host 0.0.0.0 --port 8000
```

三行要在**同一个终端**里连着敲（`export` 只对当前终端有效）。

### ✅ 成功的样子

```
INFO powercontext.server.factory PowerContext Server is ready  event="server.ready"
INFO uvicorn Application startup complete.
INFO uvicorn Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

**看到最后一行，终端就停在那里不动了——这不是卡住。** 它是个前台服务，之后只会把请求日志打在这个窗口里，不会返回命令提示符。接下来请**新开一个终端**做后面的步骤，不要在这个窗口按 Ctrl+C。

开头如果出现 `Inference capability notice … 未配置推理模型`，那是提示不是错误：本作品只用显式记忆，不需要推理模型。

### 三行命令各自的作用

| 变量 | 作用 |
| --- | --- |
| `POWERCONTEXT_HOME` | 把记忆库固定在这个目录（默认在系统用户数据目录，换终端/重启后不好找） |
| `POWERCONTEXT_SERVER_ALLOW_UNAUTHENTICATED_NON_LOOPBACK=true` | PowerContext 默认拒绝「非回环地址 + 无鉴权」启动。Dify 跑在容器里，必须监听 `0.0.0.0` 才连得上，所以本地演示要显式开这个开关（生产环境应改用 Bearer token 鉴权） |

### 这里最常见的三个错

| 报错 | 原因 | 解决 |
| --- | --- | --- |
| `refusing to bind an unauthenticated Server to a non-loopback address` | 漏了第二个变量 | 补上 `export POWERCONTEXT_SERVER_ALLOW_UNAUTHENTICATED_NON_LOOPBACK=true` |
| `Invalid value for --port` 或端口被占用 | 端口写错 | 是 **8000**，不是 80000 |
| `command not found: powercontext` | 没装成功 | 按 README 4.1 安装：`uv pip install "powercontext[cli,server]==1.4.1"`，然后改用 `powercontext server run …` |

---

## 2. 终端 B：验证记忆库活着

```bash
curl -s http://127.0.0.1:8000/health/live
```

期望 `{"status":"ok"}`。**不是这个就先别往下走**，回终端 A 看报错。

---

## 3. 终端 B：启动 Dify

```bash
cd ~/dify/docker
docker compose up -d
docker compose ps
```

### ✅ 看什么判断起好了

| 服务 | 期望 |
| --- | --- |
| `db_postgres` / `redis` / `sandbox` / `api` | `Up (healthy)` |
| `nginx` | `Up`，并且 `0.0.0.0:80->80/tcp` |
| `web` / `worker` / `worker_beat` / `plugin_daemon` / `weaviate` / `ssrf_proxy` / `api_websocket` | `Up` |

第一次启动要 1–2 分钟，`api` 会先跑数据库迁移；可以隔十几秒再 `docker compose ps` 一次，直到 `api` 变 `healthy`。

> `agent_backend` / `local_sandbox` 两个容器反复 `Restarting` **不影响这个游戏**（它们属于 Dify 的 Agent/协作功能，本应用只用 Chatflow + HTTP 节点）。想让列表干净可以停掉：
> `docker compose stop agent_backend local_sandbox`

### 让 Dify 能连到记忆库

```bash
docker compose exec api curl -s http://host.docker.internal:8000/health/live
```

期望 `{"status":"ok"}`。**这一步是关键**：Dify 的四个 HTTP 节点都通过应用环境变量 `POWERCONTEXT_BASE_URL`（默认 `http://host.docker.internal:8000`）访问记忆库；容器如果连不上，游戏里就会显示「卷宗柜打不开」。连不上时看 [README 4.2](README.md) 的 `extra_hosts` 与 `SSRF_PROXY_ALLOW_PRIVATE_IPS` 两节。

---

## 4. 终端 B：拿到访问地址

```bash
ip -4 addr show eth0 | grep -oP 'inet \K[\d.]+'
```

输出类似 `172.17.58.240`，拼成 `http://172.17.58.240/` 在浏览器打开。

### 为什么 `hostname -I` 会列出好几个地址

`hostname -I` 会把所有网卡上的 IPv4 都列出来。在装了 Docker 的 WSL 里，除了 WSL 自己的地址，还有每个 Docker 网络的桥接网关：

| 地址 | 是什么 |
| --- | --- |
| `172.17.58.240`（`eth0`） | **WSL 虚拟机自己的地址 → 浏览器要用这个** |
| `172.18.0.1` | `docker0` 默认桥接 |
| `172.19.0.1` / `172.20.0.1` / `172.21.0.1` / `172.22.0.1` | Dify 的 `agent_sandbox` / `local_sandbox_proxy` / `ssrf_proxy` / `default` 网络网关 |

以 `.1` 结尾的那些只在虚拟机内部使用，从 Windows 浏览器访问不到。所以要取 `eth0` 的那个，上面的 `ip -4 addr show eth0 …` 命令只输出它。

### 为什么不能用 `http://localhost/`

Windows 的 80 端口被本机 Apache/PHP 占着，`localhost` 会去到 Apache 而不是 WSL 里的 Dify。**必须用 WSL 的 IP。**

WSL 每次重启 IP 都可能变，所以每次都现查一次。

---

## 5. 登录

1. 浏览器打开 `http://<WSL IP>/`
2. 用你的 Dify 账号登录
3. 左侧 **工作室**（Studio）→ 应用卡片 **🐱 喵喵法庭**（CHATFLOW）
4. 进应用后点右上 **预览**，右侧弹出对话窗

> 应用已发布，`预览` 与 WebApp 里玩的是同一条工作流。

### 本机演示账号

| 项 | 值 |
| --- | --- |
| 邮箱 | `meow@example.com` |
| 密码 | `MeowCourt#2026` |

用这个账号登录就能直接看到「喵喵法庭」。换一台机器 / 重建 Dify 实例时才需要另建账号，但**新账号是空工作区，里面没有这个游戏**——应用属于工作区，不属于账号。

### 忘了密码

```bash
cd ~/dify/docker
docker compose exec -T api flask reset-password \
  --email meow@example.com \
  --new-password 'NewPassw0rd!' \
  --password-confirm 'NewPassw0rd!'
```

改完直接用新密码登录。

---

## 5.5 想重新开始（把前科清零）

卷宗是按「玩家」存的，玩家由 Dify 的 `sys.user_id` 决定。所以有两种玩法：

### 方式一：换一个玩家（推荐，最省事）

开一个**无痕窗口**打开 Dify（或在别的浏览器里登录），等于新的 `sys.user_id` → 全新空卷宗：

- 案号回到 **第 1 号**
- 累犯 **★☆☆☆☆（前科 0 次）**
- 判词会说「本庭第一次见你」

用 API 玩时把 `user` 换成新名字效果一样：

```bash
curl -X POST 'http://<dify>/v1/chat-messages' \
  -H 'Authorization: Bearer <app-API-key>' -H 'Content-Type: application/json' \
  -d '{"inputs":{},"query":"我把猫罐头换成了减肥罐头","response_mode":"blocking","user":"new-player","conversation_id":""}'
```

### 方式二：清空当前玩家已有的前科

不想换玩家、就想让手上这个账号从第 1 号重来：

先在仓库的 `dify/` 目录下（脚本只用标准库，Windows 的 python / WSL 的 python3 都能跑）：

```bash
# Windows PowerShell
cd F:\OceanBase\powercontext\cpt-powercontext\dify
python scripts\reset_player.py --user <你的 player 标识>

# WSL
cd /mnt/f/OceanBase/powercontext/cpt-powercontext/dify
python3 scripts/reset_player.py --user <你的 player 标识>

# 只想看看会清掉几条（不改数据）：加 --dry-run
```

（默认连 `http://127.0.0.1:8000`；PowerContext 不在本机就加 `--base-url http://<host>:8000`。）

**player 标识怎么找**：就是 Dify 的 `sys.user_id`。

- Web 界面：Dify 的「日志与标注 → 运行历史」点开任意一次运行，输入里 `user_id` 就是
- API：你调用时传的 `user`

脚本用 PowerContext 的 `POST /v1/atomic-memory/lifecycle`（`state=forgotten`）把案底软删除：**数据不物理删除，但列表和计数不再包含它们**，所以下次开庭就是第 1 号。实测输出：

```
玩家 789aabe2-…（Scope scp_1t5dj…）
当前案底：8 条
  已清空 art_29308818…
  …
清空后案底：0 条 → 下次开庭是第 1 号
```

> 只想清掉全部玩家、彻底重来时：停掉 PowerContext，删掉 `~/pcdata/powercontext.db*`，再启动即可（Dify 侧不用动）。

## 6. 开始玩

打开对话窗，会看到开庭白：

```
⚖️ 喵喵法庭，现在开庭。
我是本庭法官🐱橘座。你和我的每一笔恩怨都会被记进 PowerContext 卷宗，下次开庭照样有效。
· 直接描述你这次干了什么（例：我把猫罐头换成了减肥罐头）
· 输入「查卷宗」查看全部案底
· 「认罪」「辩解」「嫁祸」「撤诉」都行，本庭会酌情加刑
```

两种玩法：

| 你说什么 | 会发生什么 |
| --- | --- |
| 一段「罪行」自述，比如「我把猫罐头换成了减肥罐头」 | **开庭审判**：翻卷宗 → 定罪名 → 写判词 → 判刑 → 记进卷宗 |
| 说「查卷宗」（或 案底 / 查卷 / 前科 / 档案 / 记录） | **直接念卷宗**：不调用模型，把 PowerContext 里存的案底原样列出来 |

### 判决书长这样

```markdown
## ⚖️ 第 2 号 · 喵喵法庭开庭

**累犯等级**：★★☆☆☆（前科 1 次）
**案由**：凌晨三点劫猫离键
**被告态度**：认罪——但你这语气不像认错，像在汇报一件好人好事

**判词**：
> 第 1 号案你偷换罐头还嫁祸本猫，本庭念你初犯给了你体面；如今第 2 号……

**刑罚**：判被告上缴 4 罐正经罐头，并把那块键盘拆下来铺进纸箱……
**附加条款**：本猫趴键盘属于办公，被告抱走本猫属于越权执法。
**援引旧案**：第 1 号

—— 法槌落下——退庭。

> 🗄 本案已归档到 PowerContext 卷宗：`art_4a64f74d…`（下次开庭自动翻出）
```

**每一行都有用**：

- **案号**：第几次开庭，= 你的前科数 + 1
- **累犯等级**：0 条案底 ★☆☆☆☆，1–2 条 ★★☆☆☆，3–4 条 ★★★☆☆，5–6 条 ★★★★☆，≥7 条 ★★★★★
- **援引旧案**：法官必须引用前面某一次的案件编号；卷宗为空时它会说「本庭第一次见你」
- **归档回执**：最下面那行 `art_...` 是这条记忆在 PowerContext 里的真实编号

> 判词要等模型输出，通常 5–20 秒。

---

## 7. 五句话体验完整玩法

按顺序说这五句，完整体验「初犯 → 累犯 → 跨会话 → 通缉令 → 查卷宗」：

1. `我把猫罐头换成了减肥罐头，还说是猫自己说要减肥`
   → 第 1 号，★☆☆☆☆，判词说「本庭第一次见你」
2. `我昨晚三点把你从键盘上抱走了`
   → 第 2 号，★★☆☆☆，判词**主动引用第 1 号**
3. **点预览窗右上角的 ↻ 开新会话**，再说：`我把你的纸箱扔了，还说是风干的`
   → 第 3 号，★★★☆☆；**新会话里它依然记得前两次**
4. `我把你的猫粮偷吃了，还说是你自己吃腻了`
   → 第 4 号，★★★★☆，判词里开始出现【通缉令】
5. `查卷宗`
   → 直接把 4 条案底原文列出来（这一步不花模型额度）

> 第 3 步是重点：**新会话**里 Dify 的会话变量已被清空，案号和前科次数只能来自 PowerContext，这就是「它真的记得」。

---

## 8. 其它可玩的操作

| 想干什么 | 怎么做 |
| --- | --- |
| 换个身份重新开始 | 开一个无痕窗口（= 新的 Dify 用户），或调 API 时把 `user` 换成新名字；只想清空当前玩家的前科见第 5.5 节 |
| 扮演更离谱的被告 | 「我不认罪，是风干的」「我要反诉你抓伤我」「我申请换法官」——法官会照着卷宗吐槽 |
| 看它记不记得细节 | 先犯一次具体的错（比如「我把你的猫砂盆换成了狗砂盆」），之后说「查卷宗」看原文 |
| 一次塞几条前科 | `python scripts/seed_demo_memory.py --base-url http://127.0.0.1:8000 --user <玩家名>`（写第 1–3 号，幂等） |
| 用 API 玩 | 见 README 6.4：`POST /v1/chat-messages`，`user` 是玩家标识，`conversation_id` 传空 = 新会话 |

---

## 9. 玩不了怎么办

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 启动 PowerContext 报 `refusing to bind … non-loopback address` | 少了开关 | 补 `export POWERCONTEXT_SERVER_ALLOW_UNAUTHENTICATED_NON_LOOPBACK=true` |
| `Invalid value for --port` / 端口被占用 | 端口写错或已有实例 | 端口是 **8000**；先 `pkill -f "powercontext server run"` 再起 |
| 浏览器打不开 / 打开是别的网站 | 用了 `localhost`，或 IP 变了 | 用 `ip -4 addr show eth0` 现查 IP，别用 `localhost` |
| 回复「⚠️ 卷宗柜打不开」 | Dify 连不上 PowerContext | 终端 B 跑 `docker compose exec api curl -s http://host.docker.internal:8000/health/live`；不通见 README 4.2 |
| 报「模型不存在 / Provider does not exist」 | Dify 没配模型 | 设置 → 模型供应商 → 安装并配置 DeepSeek（或任一聊天模型）；再回工作流把 `橘座法官` 节点模型重选一次 |
| 判词变成一大段纯文本，没有「案由/刑罚」 | 模型没按 JSON 输出 | 走了降级路径（判决仍会归档）。换更强模型或降低温度重试 |
| 累犯星级不涨 | 换了身份（换浏览器/换 user = 新卷宗） | 用「查卷宗」确认条目数；想累加就用同一个浏览器 |
| 查卷宗是空的 | 这个身份还没犯过事 | 先说一句罪行，再来查 |
| `docker compose ps` 里两个容器反复 Restarting | Dify 的 Agent 组件 | 与游戏无关，可 `docker compose stop agent_backend local_sandbox` |

---

## 10. 玩完怎么关

```bash
# 终端 B：关 Dify（只停容器和网络，数据都在）
cd ~/dify/docker && docker compose down

# 终端 A：关 PowerContext
Ctrl + C
```

- 案底：`~/pcdata` 里的 SQLite，保留
- Dify 的应用、账号、模型配置：docker volume 里，保留
- 下次按第 1、3 步重新起即可，案底还在；但 **WSL 重启后 IP 会变**，记得重新 `ip -4 addr show eth0`。
