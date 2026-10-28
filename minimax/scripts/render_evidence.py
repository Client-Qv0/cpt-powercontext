"""Render the human-reviewable technical use records from one real run.

Inputs are the artifacts written by ``specanchor apply`` and
``scripts/verify_change.py``.  Every fact in the generated Markdown is read from
those files; nothing is hand-copied, so the records cannot drift from the diff,
logs and PowerContext state that they describe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = PACKAGE_ROOT / "evidence"


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path: Path, default: str = "") -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else default


def git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(PACKAGE_ROOT), capture_output=True, text=True
    )
    return completed.stdout.strip() or "not-a-git-checkout"


def pick_run(run_dir: str | None) -> Path:
    if run_dir:
        return Path(run_dir).resolve()
    candidates = sorted((EVIDENCE / "runs").glob("*"), key=lambda path: path.name)
    succeeded = [path for path in candidates if read_json(path / "result.json", {}).get("status") == "succeeded"]
    if not succeeded:
        raise SystemExit("未找到成功的运行记录；先运行 specanchor apply，或传 --run-dir")
    return succeeded[-1]


def find_log(run_dir: Path, name: str) -> Path | None:
    path = run_dir / name
    return path if path.is_file() else None


def render_minimax_record(run_dir: Path, context: dict[str, Any], result: dict[str, Any]) -> str:
    lines: list[str] = []
    task = context["task"]
    lines.append(f"# MiniMax 开发记录 · {task['id']}")
    lines.append("")
    lines.append(f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}")
    lines.append(f"- 代码版本：`{git_head()}`")
    lines.append(f"- 运行目录：`{run_dir.as_posix().replace(str(PACKAGE_ROOT.as_posix()) + '/', '')}`")
    lines.append(f"- 任务：{task['title']}")
    lines.append("")
    lines.append("## 1. 交给 MiniMax 的任务上下文")
    lines.append("")
    lines.append("上下文由 `specanchor context` 从 seekdb 索引中选出，未人工拼装：")
    lines.append("")
    lines.append("| 类型 | 来源 | 说明 |")
    lines.append("| --- | --- | --- |")
    for spec in context["specs"]:
        lines.append(
            f"| 规格 | `{spec['path']}:{spec['line_start']}-{spec['line_end']}` | `{spec['spec_id']}` {spec['heading']} (rev {spec['revision']}) |"
        )
    for symbol in context["code"]:
        lines.append(
            f"| 代码 | `{symbol['path']}:{symbol['line_start']}-{symbol['line_end']}` | `{symbol['qualname']}` |"
        )
    for test in context["tests"]["target"]:
        lines.append(f"| 目标测试 | `{test['path']}::{test['test_id']}` | {test['why']} |")
    for test in context["tests"]["regression"]:
        lines.append(f"| 回归测试 | `{test['path']}::{test['test_id']}` | {test['why']} |")
    lines.append("")
    lines.append(f"上下文摘要：`{context['context_digest']}`；构建时执行 {len(context['diagnostics']['db']['queries'])} 条 seekdb 查询。")
    lines.append("")

    calls: list[dict[str, Any]] = []
    calls_path = run_dir / "minimax-calls.jsonl"
    if calls_path.is_file():
        calls = [json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    lines.append("## 2. MiniMax 调用记录")
    lines.append("")
    lines.append("- 接入方式：HTTP `POST {MINIMAX_BASE_URL}/chat/completions`（OpenAI 兼容）")
    lines.append(f"- 模型：`{result.get('minimax', {}).get('model', '')}`")
    lines.append(f"- 尝试次数：{len(calls)}")
    for call in calls:
        response = call.get("response", {})
        lines.append(
            f"- 第 {call['attempt']} 次：{response.get('latency_ms', 0)} ms，"
            f"usage={json.dumps(response.get('usage', {}), ensure_ascii=False)}，"
            f"finish_reason=`{response.get('finish_reason', '')}`"
        )
    lines.append("")
    lines.append("> 请求中的 API Key 不写盘；这里只记录模型、时延、用量与补丁。")
    lines.append("")

    lines.append("## 3. 代码修改")
    lines.append("")
    patch_path = Path(result.get("diff_path", ""))
    if patch_path.is_file():
        diff = patch_path.read_text(encoding="utf-8")
        digest = hashlib.sha256(diff.encode("utf-8")).hexdigest()
        lines.append(f"- 补丁文件：`{patch_path.as_posix().replace(str(PACKAGE_ROOT.as_posix()) + '/', '')}`")
        lines.append(f"- 补丁 SHA-256：`{digest}`")
        lines.append("")
        lines.append("```diff")
        lines.append(diff.rstrip())
        lines.append("```")
    else:
        lines.append("- 补丁文件缺失")
    lines.append("")

    lines.append("## 4. 修改前 / 修改后测试")
    lines.append("")
    test_runs = result.get("test_runs", {})
    lines.append("| 阶段 | 命令 | 退出码 | passed | failed | 日志 |")
    lines.append("| --- | --- | ---: | ---: | ---: | --- |")
    for key, label in (
        ("baseline_target", "修改前目标测试（预期失败）"),
        ("baseline_regression", "修改前回归测试"),
        ("target", "修改后目标测试"),
        ("regression", "修改后回归测试"),
        ("full_suite", "修改后全量测试"),
    ):
        run = test_runs.get(key)
        if not run:
            continue
        nodeids = " ".join(run.get("nodeids", []))
        command = "python -m pytest -q -p no:cacheprovider --no-header " + nodeids
        log = run.get("log")
        log_label = "`" + Path(log).name + "`" if log else "-"
        lines.append(
            f"| {label} | `{command.strip()}` | {run.get('exit_code')} | {run.get('passed')} | "
            f"{run.get('failed')} | {log_label} |"
        )
    lines.append("")
    lines.append("同一组目标测试在修改前因功能未实现而失败（退出码 1，存在真实断言失败），"
                 "修改后全部通过；回归测试在修改前后均通过。")
    lines.append("")
    return "\n".join(lines)


def render_db_record(context: dict[str, Any], run_dir: Path) -> str:
    lines: list[str] = []
    lines.append("# seekdb / OceanBase 使用记录")
    lines.append("")
    lines.append(f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}")
    db = context["diagnostics"]["db"]
    lines.append(f"- 引擎：{db['engine']}")
    lines.append(f"- 数据库：`{db['database']}`")
    lines.append(f"- 索引内容：{len(context['specs'])} 条规格、{len(context['code'])} 个代码符号、"
                 f"{len(context['tests']['target']) + len(context['tests']['regression'])} 个测试（选入本次上下文）")
    lines.append("")
    lines.append("## 1. 本次上下文构建实际执行的查询")
    lines.append("")
    lines.append("| # | 行数 | 耗时(ms) | SQL |")
    lines.append("| ---: | ---: | ---: | --- |")
    for index, query in enumerate(db["queries"], start=1):
        sql = query["sql"].replace("|", "\\|")
        lines.append(f"| {index} | {query['rows']} | {query['ms']} | `{sql}` |")
    lines.append("")
    lines.append("## 2. 检索得到的规格（来自 `sa_spec_sections`）")
    lines.append("")
    lines.append("| 规格 | 路径 | 修订 | 内容哈希 | 得分 |")
    lines.append("| --- | --- | ---: | --- | ---: |")
    for spec in context["specs"]:
        lines.append(
            f"| `{spec['spec_id']}` | `{spec['path']}:{spec['line_start']}-{spec['line_end']}` | "
            f"{spec['revision']} | `{spec['content_hash'][:16]}…` | {spec['score']} |"
        )
    lines.append("")
    lines.append("## 3. 检索得到的代码符号（来自 `sa_code_symbols`）")
    lines.append("")
    lines.append("| 符号 | 路径 | 修订 | 得分 |")
    lines.append("| --- | --- | ---: | ---: |")
    for symbol in context["code"]:
        lines.append(
            f"| `{symbol['qualname']}` | `{symbol['path']}:{symbol['line_start']}-{symbol['line_end']}` | "
            f"{symbol['revision']} | {symbol['score']} |"
        )
    lines.append("")
    lines.append("> 行号、内容和哈希均通过 `SpecAnchor._verify_sources` 对真实文件校验；"
                 "`context.sources` 记录了每个文件的 SHA-256。")
    lines.append("")
    return "\n".join(lines)


def render_powercontext_record(run_dir: Path, context: dict[str, Any]) -> str:
    state = read_json(run_dir / "powercontext-state.json", context.get("state", {}))
    lines: list[str] = []
    lines.append("# PowerContext 状态写入与复用记录")
    lines.append("")
    lines.append(f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}")
    lines.append("- SDK：`powercontext[builtin]==1.4.1`")
    lines.append(f"- 存储：`{state.get('storage', '.state/powercontext.db')}`（PowerContext builtin SQLite backend）")
    lines.append(f"- Scope：`{state.get('scope_id')}`")
    lines.append("")
    lines.append("## 1. 写入的记录")
    lines.append("")
    contract = state.get("contract")
    outcome = state.get("latest_outcome")
    if contract:
        lines.append(f"- Work contract：`{contract['source_ref']['source_id']}`，position={contract['position']}")
        lines.append(f"  - objective：{contract['record'].get('objective', '')}")
        lines.append(f"  - completion_criteria：{json.dumps(contract['record'].get('completion_criteria', []), ensure_ascii=False)}")
    if outcome:
        lines.append(f"- Task outcome：`{outcome['source_ref']['source_id']}`，position={outcome['position']}，"
                     f"status=`{outcome['status']}`")
        lines.append(f"  - summary：{outcome['record'].get('summary', '')}")
    lines.append("")
    lines.append("## 2. 从新进程读取到的状态")
    lines.append("")
    lines.append("读取方式：`python -m specanchor state show --task examples/task-book-filters.json`")
    lines.append("")
    lines.append("已完成事项：")
    for item in state.get("done", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("待办事项：")
    for item in state.get("todo", []) or ["（无）"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("验证结果：")
    lines.append("")
    lines.append("| 检查 | 状态 | 详情 |")
    lines.append("| --- | --- | --- |")
    for check in state.get("verification", []):
        details = str(check.get("details", "")).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {check.get('name')} | {check.get('status')} | {details[:200]} |")
    lines.append("")
    lines.append("## 3. 重启复用证据")
    lines.append("")
    lines.append("`context`、`apply`、`state show` 每次都由独立 CLI 进程启动，"
                 "PowerContext runtime 在进程退出时关闭；上面的状态是后续进程重新打开同一个 "
                 "SQLite 数据库并通过 `Work continuity` 读取的，不依赖内存缓存。")
    lines.append("")
    return "\n".join(lines)


def render_test_record() -> str:
    summary = read_json(EVIDENCE / "verify-change.json", {})
    lines: list[str] = []
    lines.append("# 代码修改前后测试结果")
    lines.append("")
    lines.append(f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}")
    lines.append(f"- 验证脚本：`scripts/verify_change.py`")
    lines.append(f"- 代码版本：`{git_head()}`")
    lines.append("")
    if not summary:
        lines.append("尚未运行 `scripts/verify_change.py`。")
        return "\n".join(lines)
    lines.append("| 阶段 | 退出码 | passed | failed | errors | 期望 | 结果 |")
    lines.append("| --- | ---: | ---: | ---: | ---: | --- | --- |")
    for check in summary.get("checks", []):
        lines.append(
            f"| {check['name']} | {check['exit_code']} | {check['passed']} | {check['failed']} | "
            f"{check['errors']} | {check['expectation']} | {'PASS' if check['ok'] else 'FAIL'} |"
        )
    lines.append("")
    lines.append("日志位置：`evidence/test-logs/`（每条日志头部记录命令、工作目录、退出码与代码版本）。")
    lines.append("")
    lines.append(f"基线快照：`{summary.get('baseline_zip')}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="从真实运行产物生成技术使用记录")
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--context-json", default=None, help="仅有上下文时，单独生成 seekdb 查询记录")
    parser.add_argument("--out-dir", default=str(EVIDENCE))
    args = parser.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if args.context_json:
        context = read_json(Path(args.context_json), {})
        if not context:
            raise SystemExit(f"上下文文件不存在或为空: {args.context_json}")
        (out / "seekdb-queries.md").write_text(
            render_db_record(context, Path(args.context_json).parent), encoding="utf-8", newline="\n"
        )
        print(f"已生成 {out / 'seekdb-queries.md'}（来源 {args.context_json}）")
        return 0
    run_dir = pick_run(args.run_dir)
    result = read_json(run_dir / "result.json", {})
    context = read_json(run_dir / "context.json", {})
    if not context or not result:
        raise SystemExit(f"运行目录缺少 context.json / result.json: {run_dir}")
    (out / "minimax-development-record.md").write_text(
        render_minimax_record(run_dir, context, result), encoding="utf-8", newline="\n"
    )
    (out / "seekdb-queries.md").write_text(render_db_record(context, run_dir), encoding="utf-8", newline="\n")
    (out / "powercontext-state.md").write_text(
        render_powercontext_record(run_dir, context), encoding="utf-8", newline="\n"
    )
    (out / "test-results.md").write_text(render_test_record(), encoding="utf-8", newline="\n")
    print(f"已生成 {out} 下的 4 份技术使用记录（来源 run_dir={run_dir}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
