"""Prompt construction for the MiniMax code-modification step."""

from __future__ import annotations

from pathlib import Path
from typing import Any

SYSTEM_PROMPT = """你是 MiniMax 驱动的资深软件工程师，正在执行一次规格驱动开发（SDD）任务。
你的输出会被程序直接 `git apply` 到真实工程，因此必须严格遵守：

1. 只修改 `src/` 下的实现文件；绝对不要修改 `tests/`、`specs/` 或任何配置文件。
2. 满足目标规格（target specs），同时保持所有兼容性约束（must preserve）。
3. 不要引入新依赖，不要删除或跳过测试，不要改变公开接口的字段名与类型。
4. 只输出一个 unified diff，路径相对工程根目录（a/src/...、b/src/...）。
5. 不要输出解释、Markdown 围栏、思考过程或额外的前后缀文字。
6. `@@ -a,b +c,d @@` 中的 b 与 d 必须等于该 hunk 正文实际的行数：b 是上下文行与删除行的总和，
   d 是上下文行与新增行的总和。行数写错会让补丁无法应用。
"""


def build_user_prompt(context: dict[str, Any], project_root: Path) -> str:
    lines: list[str] = []
    task = context["task"]
    lines.append("## 任务")
    lines.append(f"- id: `{task['id']}`")
    lines.append(f"- 标题: {task['title']}")
    lines.append("")
    lines.append(task["request"])
    lines.append("")

    if task["must_preserve"]:
        lines.append("## 必须保持的既有行为")
        for item in task["must_preserve"]:
            lines.append(f"- {item}")
        lines.append("")

    lines.append("## 有效规格（来自 seekdb 索引，均来自仓库真实文件）")
    for spec in context["specs"]:
        lines.append("")
        lines.append(
            f"### [{spec['spec_id']}] {spec['heading']} "
            f"({spec['path']}:{spec['line_start']}-{spec['line_end']}, revision {spec['revision']})"
        )
        lines.append(spec["text"])
    lines.append("")

    unique_files: list[str] = []
    for symbol in context["code"]:
        if symbol["path"] not in unique_files:
            unique_files.append(symbol["path"])
    lines.append("## 待修改代码（完整文件）")
    for relative in unique_files:
        path = project_root / relative
        lines.append("")
        lines.append(f"### `{relative}`")
        lines.append("```python")
        lines.append(path.read_text(encoding="utf-8").rstrip())
        lines.append("```")
        symbols = ", ".join(
            symbol["qualname"] for symbol in context["code"] if symbol["path"] == relative
        )
        lines.append(f"相关符号: {symbols}")
    lines.append("")

    lines.append("## 目标功能测试（修改前失败，修改后必须全部通过；禁止修改这些文件）")
    for test in context["tests"]["target"]:
        lines.append("")
        lines.append(f"### `{test['path']}::{test['test_id']}`")
        lines.append("```python")
        lines.append(test["source"].rstrip())
        lines.append("```")
    lines.append("")

    lines.append("## 回归测试（修改前后都必须通过；禁止修改这些文件）")
    for test in context["tests"]["regression"]:
        lines.append(f"- `{test['path']}::{test['test_id']}`")
    lines.append("")

    state = context["state"]
    if state.get("done") or state.get("todo"):
        lines.append("## PowerContext 中的任务状态")
        if state.get("done"):
            lines.append("已完成:")
            lines.extend(f"- {item}" for item in state["done"])
        if state.get("todo"):
            lines.append("待办:")
            lines.extend(f"- {item}" for item in state["todo"])
        lines.append("")

    lines.append("## 输出格式")
    lines.append("只输出一个 unified diff，例如：")
    lines.append("--- a/src/booknest/catalog.py")
    lines.append("+++ b/src/booknest/catalog.py")
    lines.append("@@ -10,6 +10,9 @@")
    lines.append(" ...")
    lines.append("不要输出围栏以外的说明文字。")
    return "\n".join(lines)
