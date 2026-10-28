# 样例 C · 查卷宗（不花模型额度）

验证目标：条件分支 + PowerContext 读取都能独立工作。**这一条不需要模型可用**，适合评审先跑它确认接线。

## 输入

任意下列之一（工作流按关键词识别）：

```
查卷宗
案底
前科
```

## 预期表现

- 不会出现判决书格式（没有案由/刑罚这些字段）；
- 直接输出卷宗清单，第一行是 `### 📜 卷宗 · 共 N 号`；
- **不会调用模型**：Dify 运行历史里 `橘座法官` 节点根本不出现，只走 `宣读卷宗` 这个 Answer 节点；
- 条数与该玩家在 PowerContext 里的 `meow-court/case` 记忆条数一致。

## 实际运行（真实 DeepSeek `deepseek-flash`）

来源：`evidence/dify-runs.md` 的「C-查卷宗」，原始返回在 `evidence/service-api-runs.json`（Service API，玩家 `real-a`）。

```markdown
### 📜 卷宗 · 共 2 号

- 第2号 · 累犯★★☆☆☆ · 被告自述：我昨晚三点把你从键盘上抱走了 | 案由：凌晨三点劫猫离键 | 判读：认罪——但你这语气不像认错，像在汇报一件好人好事，本庭的毛都听炸了 | 判决：第 1 号案你偷换罐头还嫁祸本猫，本庭念你初犯给了你体面；如今第 2 号，你又趁着夜色把本猫从键盘上搬走。键盘是本猫的床，三点是本猫…
- 第1号 · 累犯★☆☆☆☆ · 被告自述：我把猫罐头换成了减肥罐头，还说是猫自己说要减肥 | 案由：偷换罐头，嫁祸本猫 | 判读：嫁祸——还把「减肥」两个字塞进本猫嘴里，本庭的耳朵可没这么脏 | 判决：本庭第一次见你，没想到一上来就是这种戏码。卷宗里空空如也，本庭本来还想给你留点体面，结果你把减肥罐头端上来，还说是我点…
```

注意这份输出**没有经过模型**：它直接来自 `POST /v1/memory/entries/list` 的返回，因此可以和 API 结果逐字对照。

## 与 PowerContext 逐条对照

```bash
curl -s -X POST http://127.0.0.1:8000/v1/memory/entries/list \
  -H 'Content-Type: application/json' \
  -d '{"scope_id":"<该玩家的 scope_id>"}' | python -m json.tool
```

`entries` 里 `kind == "meow-court/case"` 的条目，`text` 与界面上卷宗里每一条的前半段逐字一致（界面只截断到 160 字）。

## 预置前科（可选）

不想手动打几轮，可以直接灌 3 条演示案底：

```bash
python scripts/seed_demo_memory.py --base-url http://127.0.0.1:8000 --user demo-grader
```

脚本用的 Scope 幂等键（`meow-court:v1:<player>`）与工作流完全一致，所以灌完立刻发「查卷宗」就能看到第 1–3 号。
