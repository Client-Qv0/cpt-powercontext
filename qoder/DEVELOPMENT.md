# Qoder 开发记录

本作品主要应用代码在 Qoder CLI CN 1.1.79 中实际开发。开发目录为本仓库 `qoder/`，真实会话 ID：`1051f37f-20df-4fba-9eec-9bf50bb13a68`。登录账号显示名为 `syl0814`；显示名与 UID 不是同一字段，账号 UID 尚待本人从 Qoder 账号页面核对，未使用头像地址推测 UID。

## 实际分工

- Codex：整理需求任务书 `PROJECT_BRIEF.md`、读取公开 SDK 接口、检查 Qoder 的实现、编写独立验收测试、浏览器联调、真实截图和提交材料。
- Qoder：实现 FastAPI 服务与 PowerContext 服务层、确定性来源整理管线、项目/进展/交接查询/版本状态接口、静态前端及展示站初稿；在同一会话中根据真实失败继续调试。
- Codex 的 QA 修正：原生 MemoryEntryVersion 引用字段、项目不存在时的 404、没有评测时的状态、移除过严的二次字符串筛选、来源记录类型、技术面板实际标识及运行说明。

没有把 Codex 编写的独立测试或 QA 改动宣称为 Qoder 独立完成，也没有把 Qoder 的文字完成声明直接当作测试结果。

## 开发过程

1. 向 Qoder 提供任务书，要求完成“记录进展 → PowerContext 持久化 → 重启 → 查询原文与交接上下文”闭环。
2. 初稿猜测 SDK 接口且存在静默降级，复核后要求使用真实 builtin runtime，先跑最小纵向链路。
3. 根据实际 SDK 行为，采用 `ProgressContentPipeline.extract()`、`capture()`、`memory.flush()`，由 SDK 建立原生 SourceRef 血缘；用 FTS 检索和 Records API 取回原文。
4. Qoder 完成 `record_kind=progress/code/evaluation`、版本对照与 UI。独立验收曾发现正文检索、引用字段、无评测状态和错误码问题，修复后测试通过。
5. 同一 Qoder 会话继续完善来源展开、prepared context、虚构示例标记、技术证明与页面。最终浏览器核验并保存真实运行截图。

可核对的 Qoder 可见输出/工具调用摘录见 `evidence/qoder-session-excerpt.md`。摘录来自实际执行事件，省略了内部推理、原始工具大段输出和凭据；摘录不是 Qoder 原生界面的截图。赛事要求的关键对话截图或录屏应从该真实会话补充，不能用重新绘制的界面代替。

## 实际验证

2026 年 10 月 27 日，独立 Python 3.12.3 环境从公开 Git revision 安装 PowerContext SDK，最终执行：

```bash
python -m pytest -q tests/test_independent_acceptance.py
```

结果为 `12 passed`。检验实际的 SDK 来源、记忆、原文引用、重启、隔离、版本状态和 HTTP 行为；其中一项为专门的故障注入，验证运行异常返回 503。前端 JavaScript 通过 `node --check static/app.js`。浏览器实际执行了项目概览、交接查询、引用展开、版本对照和技术面板。

这些是本地验证结果，不是赛事平台得分。没有提交本赛题的平台评测；Qoder Sites 的公开 URL、账号 UID、原生对话截图在具备后另行补齐。

## 第三方与复用

PowerContext 官方上游为 https://github.com/oceanbase/powercontext ，许可证 Apache-2.0。本作品使用参赛仓库中固定的公开 SDK revision `6d56d1ae5a0f944e04f70233d04f2b8c010b1f7b`，依赖地址见 `backend/requirements.txt`。RelayDesk 的新增应用位于 `qoder/`；没有把整个 SDK 算作本作品新开发的代码。
