"""Command line entry point: ``python -m specanchor ...``."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

from .config import PACKAGE_ROOT, Settings
from .db import Database, resolve_project_root
from .errors import SpecAnchorError
from .ingest import import_project
from .retrieve import ContextBuilder, Task, render_markdown
from .state import StateStore, reset_state


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


def _task(args: argparse.Namespace) -> Task:
    return Task.load(Path(args.task).resolve())


def _project(args: argparse.Namespace, task: Task) -> str:
    return getattr(args, "project", None) or task.project


def _root(settings: Settings, args: argparse.Namespace) -> Path:
    return resolve_project_root(settings, getattr(args, "root", None))


def _empty_state(task: Task, project: str) -> dict[str, Any]:
    return {
        "provider": "PowerContext (empty state)",
        "scope_id": None,
        "task_id": task.id,
        "contract": None,
        "latest_outcome": None,
        "done": [],
        "todo": [],
        "verification": [],
        "events": [],
        "event_count": 0,
    }


def _build_context(settings: Settings, task: Task, project: str, root: Path, *, with_state: bool = True) -> dict[str, Any]:
    database = Database(settings)
    state = (
        asyncio.run(_read_state(settings, task.id, project))
        if with_state
        else _empty_state(task, project)
    )
    builder = ContextBuilder(database, project, root)
    return builder.build(task, state)


async def _read_state(settings: Settings, task_id: str, project: str) -> dict[str, Any]:
    async with StateStore(settings) as store:
        return await store.snapshot(task_id, project)


def cmd_db_init(args: argparse.Namespace) -> int:
    settings = Settings.load()
    database = Database(settings)
    statements = database.init_schema()
    info = database.ping()
    print(f"seekdb/OceanBase 连接成功: {info.get('version')} / database={info.get('db')}")
    print(f"已执行 {len(statements)} 条建表语句")
    return 0


def cmd_db_ping(args: argparse.Namespace) -> int:
    settings = Settings.load()
    print(json.dumps(Database(settings).ping(), ensure_ascii=False, indent=2))
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    settings = Settings.load()
    root = _root(settings, args)
    task = _task(args) if args.task else None
    project = args.project or (task.project if task else "booknest")
    database = Database(settings)
    result = import_project(database, project, root, reset=args.reset)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    settings = Settings.load()
    task = _task(args)
    project = _project(args, task)
    root = _root(settings, args)
    context = _build_context(settings, task, project, root)
    if args.out:
        out = Path(args.out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"上下文已写入 {out}")
    if args.json:
        print(json.dumps(context, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(context))
    if args.trace:
        trace_path = settings.state_dir / "last-context-queries.json"
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text(
            json.dumps(context["diagnostics"]["db"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nSQL 追踪已写入 {trace_path}")
    return 0


def cmd_state_show(args: argparse.Namespace) -> int:
    settings = Settings.load()
    task = _task(args)
    project = _project(args, task)
    state = asyncio.run(_read_state(settings, task.id, project))
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


def cmd_state_reset(args: argparse.Namespace) -> int:
    settings = Settings.load()
    removed = reset_state(settings)
    if removed:
        print("已删除 PowerContext 状态文件:")
        for path in removed:
            print(f"- {path}")
    else:
        print("PowerContext 状态文件不存在，无需清理")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    from .agent import run_apply

    settings = Settings.load()
    task = _task(args)
    outcome = asyncio.run(
        run_apply(
            settings,
            Path(args.task).resolve(),
            project=_project(args, task),
            project_root=_root(settings, args),
            max_attempts=args.max_attempts,
            dry_run=args.dry_run,
        )
    )
    print(json.dumps(outcome.as_dict(), ensure_ascii=False, indent=2))
    if outcome.status == "failed":
        return 1
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    from .agent import run_pytest

    settings = Settings.load()
    task = _task(args)
    project = _project(args, task)
    root = _root(settings, args)
    context = _build_context(settings, task, project, root)
    target_ids = [item["path"] + "::" + "::".join(item["test_id"].split(".")) for item in context["tests"]["target"]]
    regression_ids = [item["path"] + "::" + "::".join(item["test_id"].split(".")) for item in context["tests"]["regression"]]
    target = run_pytest(root, target_ids, name="verify.target")
    regression = run_pytest(root, regression_ids, name="verify.regression")
    ok = target.ok and regression.ok
    summary = {
        "task": task.id,
        "status": "passed" if ok else "failed",
        "target": target.as_dict(),
        "regression": regression.as_dict(),
        "specs": [item["spec_id"] for item in context["specs"]],
        "context_digest": context["context_digest"],
    }
    if args.record:
        async def record() -> None:
            async with StateStore(settings) as store:
                await store.record_outcome(
                    task_id=task.id,
                    project=project,
                    run_id=f"verify-{uuid.uuid4().hex[:8]}",
                    objective=f"{task.title}：{task.request[:600]}",
                    status="succeeded" if ok else "failed",
                    summary="独立验证：目标测试与回归测试" + ("全部通过" if ok else "存在失败"),
                    observations=[
                        f"目标测试 {target.passed} passed / {target.failed} failed",
                        f"回归测试 {regression.passed} passed / {regression.failed} failed",
                    ],
                    checks=[
                        {
                            "name": "verify.target",
                            "status": "passed" if target.ok else "failed",
                            "details": f"exit={target.exit_code}",
                        },
                        {
                            "name": "verify.regression",
                            "status": "passed" if regression.ok else "failed",
                            "details": f"exit={regression.exit_code}",
                        },
                    ],
                    remaining_work=[] if ok else ["修复失败测试后重新验证"],
                )

        asyncio.run(record())
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def cmd_spec_update(args: argparse.Namespace) -> int:
    settings = Settings.load()
    task = _task(args)
    project = f"{task.project}-specupdate"
    source_root = _root(settings, args)
    demo_root = settings.state_dir / "spec-update-demo"
    if demo_root.exists():
        shutil.rmtree(demo_root)
    shutil.copytree(
        source_root,
        demo_root,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", "pytest-cache-files-*"),
    )
    replacement = Path(args.replacement).resolve()
    if not replacement.is_file():
        raise SpecAnchorError(f"替换规格不存在: {replacement}")
    spec_rel = Path(args.spec)
    target_spec = demo_root / spec_rel
    if not target_spec.is_file():
        raise SpecAnchorError(f"样例规格不存在: {spec_rel}")

    database = Database(settings)
    before_import = import_project(database, project, demo_root, reset=True)
    before = ContextBuilder(database, project, demo_root).build(task, _empty_state(task, project))
    before_section = _find_spec(before, args.section)

    target_spec.write_text(replacement.read_text(encoding="utf-8"), encoding="utf-8")
    after_import = import_project(database, project, demo_root)
    after = ContextBuilder(database, project, demo_root).build(task, _empty_state(task, project))
    after_section = _find_spec(after, args.section)

    changed = before_section["content_hash"] != after_section["content_hash"]
    evidence = {
        "task": task.id,
        "project": project,
        "spec_file": str(spec_rel),
        "section": args.section,
        "before": before_section,
        "after": after_section,
        "changed": changed,
        "revision": {"before": before_section["revision"], "after": after_section["revision"]},
        "import_changes": after_import.changed_sections,
        "db_queries_before": len(before["diagnostics"]["db"]["queries"]),
        "db_queries_after": len(after["diagnostics"]["db"]["queries"]),
        "context_digest": {"before": before["context_digest"], "after": after["context_digest"]},
    }
    evidence_path = PACKAGE_ROOT / "evidence" / "spec-update.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: evidence[k] for k in ("section", "changed", "revision", "context_digest")}, ensure_ascii=False, indent=2))
    print(f"证据已写入 {evidence_path}")
    return 0 if changed else 1


def _find_spec(context: dict[str, Any], spec_id: str) -> dict[str, Any]:
    for item in context["specs"]:
        if item["spec_id"] == spec_id:
            return item
    raise SpecAnchorError(f"上下文未包含规格 {spec_id}")


def cmd_doctor(args: argparse.Namespace) -> int:
    settings = Settings.load()
    report: dict[str, Any] = {"settings": settings.public_summary()}
    try:
        database = Database(settings)
        report["database"] = database.ping()
        with database.session() as session:
            row = session.fetchone(
                "SELECT COUNT(*) AS tables FROM information_schema.tables WHERE table_schema=%s AND table_name LIKE 'sa_%%'",
                (settings.db_name,),
            )
        report["database"]["specanchor_tables"] = row["tables"] if row else 0
    except Exception as exc:
        report["database"] = {"ok": False, "error": str(exc)}
    report["powercontext_db_exists"] = settings.powercontext_db.exists()
    report["sample_project_exists"] = (settings.project_root / "src").is_dir()
    from shutil import which

    report["git"] = which("git")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["database"].get("ok") else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="specanchor",
        description="SpecAnchor：面向持续演进的 SDD 上下文模块（seekdb + PowerContext + MiniMax）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    db = sub.add_parser("db", help="seekdb 初始化与连通性检查")
    db_sub = db.add_subparsers(dest="db_command", required=True)
    db_sub.add_parser("init", help="创建数据库与表").set_defaults(func=cmd_db_init)
    db_sub.add_parser("ping", help="检查连接").set_defaults(func=cmd_db_ping)

    ingest = sub.add_parser("ingest", help="导入规格/代码/测试并重建索引")
    ingest.add_argument("--project", default=None)
    ingest.add_argument("--root", default=None, help="工程根目录，默认 sample_project")
    ingest.add_argument("--task", default=None, help="可选：从任务文件读取 project")
    ingest.add_argument("--reset", action="store_true", help="先删除该 project 的索引再重建")
    ingest.set_defaults(func=cmd_ingest)

    context = sub.add_parser("context", help="为任务构建开发上下文")
    context.add_argument("--task", required=True)
    context.add_argument("--project", default=None)
    context.add_argument("--root", default=None)
    context.add_argument("--json", action="store_true", help="输出完整 JSON")
    context.add_argument("--out", default=None, help="额外写入 JSON 文件")
    context.add_argument("--trace", action="store_true", help="保存 SQL 追踪")
    context.set_defaults(func=cmd_context)

    state = sub.add_parser("state", help="PowerContext 状态")
    state_sub = state.add_subparsers(dest="state_command", required=True)
    show = state_sub.add_parser("show", help="读取任务状态")
    show.add_argument("--task", required=True)
    show.add_argument("--project", default=None)
    show.set_defaults(func=cmd_state_show)
    state_sub.add_parser("reset", help="清空本地 PowerContext 数据库").set_defaults(func=cmd_state_reset)

    apply_parser = sub.add_parser("apply", help="调用 MiniMax 完成代码修改并验证")
    apply_parser.add_argument("--task", required=True)
    apply_parser.add_argument("--project", default=None)
    apply_parser.add_argument("--root", default=None)
    apply_parser.add_argument("--max-attempts", type=int, default=3)
    apply_parser.add_argument("--dry-run", action="store_true", help="只调用模型并校验补丁，不落盘")
    apply_parser.set_defaults(func=cmd_apply)

    verify = sub.add_parser("verify", help="独立运行目标与回归测试")
    verify.add_argument("--task", required=True)
    verify.add_argument("--project", default=None)
    verify.add_argument("--root", default=None)
    verify.add_argument("--record", action="store_true", help="把验证结果写入 PowerContext")
    verify.set_defaults(func=cmd_verify)

    spec_update = sub.add_parser("spec-update", help="规格更新后重新导入的验证样例")
    spec_update.add_argument("--task", required=True)
    spec_update.add_argument("--root", default=None)
    spec_update.add_argument("--spec", default="specs/catalog.md")
    spec_update.add_argument("--replacement", default=str(PACKAGE_ROOT / "examples" / "spec-update" / "catalog-v4.md"))
    spec_update.add_argument("--section", default="BOOK-004")
    spec_update.set_defaults(func=cmd_spec_update)

    doctor = sub.add_parser("doctor", help="检查依赖与配置")
    doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except SpecAnchorError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
