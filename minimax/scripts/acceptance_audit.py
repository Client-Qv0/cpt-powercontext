"""Audit the six acceptance items against the current workspace.

Run it after `apply` to confirm the submission is complete, or before to see
exactly which items are still pending.  It never calls MiniMax; it inspects the
key, the latest run artifacts, seekdb, PowerContext and the sample test suites.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from specanchor.evidence import verify_model_evidence
from specanchor.agent import run_pytest  # noqa: E402
from specanchor.config import Settings  # noqa: E402
from specanchor.db import Database  # noqa: E402
from specanchor.retrieve import ContextBuilder, Task  # noqa: E402
from specanchor.state import StateStore  # noqa: E402

TASK_PATH = PACKAGE_ROOT / "examples" / "task-book-filters.json"
EVIDENCE = PACKAGE_ROOT / "evidence"


def _nodeid(item: dict[str, Any]) -> str:
    return item["path"] + "::" + "::".join(item["test_id"].split("."))


def _latest_success(task_id: str) -> Path | None:
    candidates = sorted((EVIDENCE / "runs").glob("*"), key=lambda path: path.name)
    for path in reversed(candidates):
        result = path / "result.json"
        if not result.is_file():
            continue
        try:
            payload = json.loads(result.read_text(encoding="utf-8"))
            if payload.get("status") == "succeeded" and payload.get("task_id") == task_id:
                return path
        except ValueError:
            continue
    return None


async def _state_snapshot(settings: Settings, task_id: str, project: str) -> dict[str, Any]:
    async with StateStore(settings) as store:
        return await store.snapshot(task_id, project)


def main() -> int:
    parser = argparse.ArgumentParser(description="六项验收自检")
    parser.add_argument("--task", default=str(TASK_PATH))
    parser.add_argument("--out", default=str(EVIDENCE / "acceptance-audit.json"))
    parser.add_argument("--strict", action="store_true", help="存在 pending/fail 时返回非零")
    args = parser.parse_args()

    settings = Settings.load()
    task = Task.load(Path(args.task))
    checks: list[dict[str, Any]] = []

    def add(item: str, status: str, detail: str) -> None:
        checks.append({"item": item, "status": status, "detail": detail})

    # 1. Runnable: database reachable and a real context build succeeds.
    database = Database(settings)
    runnable_ok = False
    runnable_details: list[str] = []
    context: dict[str, Any] | None = None
    try:
        ping = database.ping()
        runnable_ok = True
        runnable_details.append(f"seekdb {ping.get('version')} / db={ping.get('db')}")
    except Exception as exc:
        runnable_details.append(f"数据库不可用: {exc}")

    if runnable_ok:
        try:
            context = ContextBuilder(database, task.project, settings.project_root).build(
                task,
                {
                    "provider": "audit",
                    "scope_id": None,
                    "done": [],
                    "todo": [],
                    "verification": [],
                    "events": [],
                },
            )
            runnable_details.append("上下文构建成功")
        except Exception as exc:
            runnable_ok = False
            runnable_details.append(f"上下文构建失败: {exc}")
    add("能够运行", "pass" if runnable_ok else "fail", "; ".join(runnable_details))

    context_ok = False
    context_detail = "未构建上下文"
    if context is not None:
        spec_ids = {item["spec_id"] for item in context["specs"]}
        code = {item["qualname"] for item in context["code"]}
        target = context["tests"]["target"]
        regression = context["tests"]["regression"]
        sources_ok = all(item["exists"] for item in context["sources"])
        context_ok = (
            {"BOOK-004", "BOOK-005", "API-001"} <= spec_ids
            and "CatalogService.list_books" in code
            and len(target) == 8
            and len(regression) >= 10
            and sources_ok
        )
        context_detail = (
            f"规格 {len(spec_ids)} 条 / 目标 {len(target)} / 回归 {len(regression)}，"
            f"来源全部存在={sources_ok}"
        )
        db_queries = context["diagnostics"]["db"]["queries"]
        add("数据库实际参与", "pass" if db_queries else "fail", f"本次上下文执行 {len(db_queries)} 条 seekdb 查询")

    spec_update = EVIDENCE / "spec-update.json"
    spec_update_ok = False
    spec_update_detail = "规格更新证据缺失，先运行 specanchor spec-update"
    if spec_update.is_file():
        payload = json.loads(spec_update.read_text(encoding="utf-8"))
        revision = payload.get("revision", {})
        spec_update_ok = bool(payload.get("changed")) and revision.get("after", 0) > revision.get("before", 0)
        spec_update_detail = f"规格 revision {revision.get('before')}→{revision.get('after')}"

    if context_ok and spec_update_ok:
        add("上下文正确", "pass", f"{context_detail}；{spec_update_detail}")
    elif context_ok and not spec_update_ok:
        add("上下文正确", "pending", f"{context_detail}；{spec_update_detail}")
    elif spec_update.is_file() and not spec_update_ok:
        add("上下文正确", "fail", f"{context_detail}；{spec_update_detail}")
    else:
        add("上下文正确", "fail", context_detail)

    # 3. MiniMax participation.
    latest = _latest_success(task.id)
    if latest is not None:
        try:
            proof = verify_model_evidence(latest, task.id)
            add("MiniMax 实际参与", "pass", f"本地调用/响应/补丁/测试记录一致：{proof['model']}；不代表远端认证")
        except Exception as exc:
            add("MiniMax 实际参与", "fail", str(exc))
    else:
        add("MiniMax 实际参与", "pending", "尚无成功运行证据；重新调用模型需要密钥")

    # 4. PowerContext reuse.
    try:
        state = asyncio.run(_state_snapshot(settings, task.id, task.project))
        if state.get("contract") and state.get("latest_outcome"):
            add("状态能够复用", "pass", f"scope={state.get('scope_id')}，事件 {state.get('event_count')} 条")
        else:
            add("状态能够复用", "pending", "PowerContext 尚无 contract/outcome；运行 apply 后写入")
    except Exception as exc:
        add("状态能够复用", "fail", f"PowerContext 读取失败: {exc}")

    # 5. Code-change effectiveness.
    if context is not None:
        target_ids = [_nodeid(item) for item in context["tests"]["target"]]
        regression_ids = [_nodeid(item) for item in context["tests"]["regression"]]
        target_run = run_pytest(settings.project_root, target_ids, name="audit.target")
        regression_run = run_pytest(settings.project_root, regression_ids, name="audit.regression")
        if target_run.ok and regression_run.ok:
            add("代码修改有效", "pass", f"目标 {target_run.passed} passed，回归 {regression_run.passed} passed")
        elif not target_run.ok and regression_run.ok:
            add("代码修改有效", "pending", f"仍为修改前基线：目标 {target_run.failed} failed，回归 {regression_run.passed} passed")
        else:
            add("代码修改有效", "fail", f"目标 exit={target_run.exit_code}，回归 exit={regression_run.exit_code}")

    audit = {
        "task": task.id,
        "workspace": str(PACKAGE_ROOT),
        "checks": checks,
        "summary": {
            "pass": sum(1 for item in checks if item["status"] == "pass"),
            "pending": sum(1 for item in checks if item["status"] == "pending"),
            "fail": sum(1 for item in checks if item["status"] == "fail"),
        },
        "latest_success_run": str(latest) if latest else None,
        "minimax_key_configured": bool(settings.minimax_api_key),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    print(f"{'验收项':<18} {'状态':<8} 说明")
    for item in checks:
        print(f"{item['item']:<18} {item['status']:<8} {item['detail']}")
    print(f"\n汇总: pass={audit['summary']['pass']} pending={audit['summary']['pending']} fail={audit['summary']['fail']}")
    print(f"报告: {out}")
    if audit["summary"]["fail"]:
        return 1
    if args.strict and audit["summary"]["pending"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
