"""End-to-end SDD run: context -> MiniMax -> patch -> tests -> PowerContext."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import PACKAGE_ROOT, Settings
from .db import Database
from .errors import MiniMaxError, PatchError, SpecAnchorError, VerificationError
from .ingest import import_project
from .minimax import MiniMaxClient
from .patch import apply_diff, extract_unified_diff, normalize_hunk_headers, validate_diff
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .retrieve import ContextBuilder, Task
from .state import StateStore

PASSED_RE = re.compile(r"(\d+) passed")
FAILED_RE = re.compile(r"(\d+) failed")
ERROR_RE = re.compile(r"(\d+) errors?")
EVIDENCE_DIR = PACKAGE_ROOT / "evidence"


@dataclass
class TestRun:
    name: str
    nodeids: list[str]
    exit_code: int
    output: str
    duration_s: float
    passed: int = 0
    failed: int = 0
    errors: int = 0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def environment_error(self) -> bool:
        if self.exit_code in {2, 3, 4, 5}:
            return True
        if "ERROR collecting" in self.output or "errors during collection" in self.output:
            return True
        return False

    def as_dict(self, log_path: str | None = None) -> dict[str, Any]:
        return {
            "name": self.name,
            "nodeids": self.nodeids,
            "exit_code": self.exit_code,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "duration_s": round(self.duration_s, 3),
            "log": log_path,
        }


def _nodeid(entry: dict[str, Any]) -> str:
    return entry["path"] + "::" + "::".join(entry["test_id"].split("."))


def run_pytest(project_root: Path, nodeids: list[str], *, name: str, timeout: int = 300) -> TestRun:
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header"]
    command.extend(nodeids)
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = str(project_root / "src") + (os.pathsep + existing if existing else "")
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=environment,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        output = f"pytest timed out after {timeout}s\n{exc.stdout or ''}\n{exc.stderr or ''}"
        exit_code = 124
    duration = time.perf_counter() - started
    run = TestRun(
        name=name,
        nodeids=nodeids,
        exit_code=exit_code,
        output=output,
        duration_s=duration,
    )
    passed = PASSED_RE.search(output)
    failed = FAILED_RE.search(output)
    errors = ERROR_RE.search(output)
    run.passed = int(passed.group(1)) if passed else 0
    run.failed = int(failed.group(1)) if failed else 0
    run.errors = int(errors.group(1)) if errors else 0
    return run


def _write(path: Path, content: str, mode: str = "w") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode, encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def _now_slug() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


@dataclass
class ApplyOutcome:
    status: str
    run_id: str
    run_dir: str
    task_id: str
    attempts: int = 0
    diff_path: str = ""
    summary: str = ""
    checks: list[dict[str, Any]] = field(default_factory=list)
    test_runs: dict[str, Any] = field(default_factory=dict)
    minimax: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "task_id": self.task_id,
            "attempts": self.attempts,
            "diff_path": self.diff_path,
            "summary": self.summary,
            "checks": self.checks,
            "test_runs": self.test_runs,
            "minimax": self.minimax,
            "error": self.error,
        }


async def run_apply(
    settings: Settings,
    task_path: Path,
    *,
    project: str | None = None,
    project_root: Path | None = None,
    max_attempts: int = 3,
    dry_run: bool = False,
    client: MiniMaxClient | None = None,
    evidence_dir: Path | None = None,
) -> ApplyOutcome:
    task = Task.load(task_path)
    project = project or task.project
    root = (project_root or settings.project_root).resolve()
    client = client or MiniMaxClient(settings)
    evidence_root = evidence_dir or EVIDENCE_DIR
    if not client.configured:
        raise MiniMaxError(
            "未配置 MINIMAX_API_KEY：上下文构建、seekdb 检索与 PowerContext 状态不需要密钥，"
            "但 `specanchor apply` 必须调用 MiniMax。请申请 Token Plan 后写入 minimax/.env。"
        )

    run_id = f"run-{uuid.uuid4().hex[:10]}"
    run_dir = evidence_root / "runs" / f"{_now_slug()}-{task.id}-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    database = Database(settings)
    async with StateStore(settings) as store:
        state = await store.snapshot(task.id, project)
        builder = ContextBuilder(database, project, root)
        context = builder.build(task, state)
        _write(run_dir / "context.json", json.dumps(context, ensure_ascii=False, indent=2))

        base_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(context, root)},
        ]
        _write(run_dir / "prompt.md", base_messages[1]["content"])

        if dry_run:
            result = client.chat(base_messages)
            _write(run_dir / "minimax-response.txt", result.content)
            _write(run_dir / "minimax-meta.json", json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
            diff = extract_unified_diff(result.content)
            diff, header_notes = normalize_hunk_headers(diff)
            info = validate_diff(diff)
            _write(run_dir / "dry-run.diff", diff)
            outcome = ApplyOutcome(
                status="dry_run",
                run_id=run_id,
                run_dir=str(run_dir),
                task_id=task.id,
                attempts=1,
                diff_path=str(run_dir / "dry-run.diff"),
                summary="仅调用 MiniMax 并校验补丁，未应用到工作区",
                minimax={**result.as_dict(), "diff": info.as_dict()},
            )
            _write(run_dir / "result.json", json.dumps(outcome.as_dict(), ensure_ascii=False, indent=2))
            return outcome

        target_ids = [_nodeid(item) for item in context["tests"]["target"]]
        regression_ids = [_nodeid(item) for item in context["tests"]["regression"]]
        if not target_ids:
            raise VerificationError("上下文没有选出任何目标测试，无法验证修改")
        if not regression_ids:
            raise VerificationError("上下文没有选出任何回归测试，无法验证兼容性")

        contract = await store.ensure_contract(
            task_id=task.id,
            project=project,
            objective=f"{task.title}：{task.request[:600]}",
            in_scope=sorted({item["path"] for item in context["code"]}),
            completion_criteria=[
                "目标功能测试在修改前失败、修改后全部通过",
                "回归测试在修改前后均通过",
                "仅修改 src/ 下的实现文件",
            ],
        )
        _write(run_dir / "powercontext-contract.json", json.dumps(contract, ensure_ascii=False, indent=2))

        baseline_target = run_pytest(root, target_ids, name="baseline.target")
        _write(run_dir / "baseline-target.log", baseline_target.output)
        if baseline_target.environment_error:
            raise VerificationError(
                "修改前目标测试出现环境错误（而非功能失败）：\n" + baseline_target.output[-2000:]
            )
        if baseline_target.ok or baseline_target.failed == 0:
            raise VerificationError(
                "目标测试在修改前已经通过，样本无法证明本次修改有效。"
                "请用 scripts/reset_sample.py 还原基线后重试。"
            )
        baseline_regression = run_pytest(root, regression_ids, name="baseline.regression")
        _write(run_dir / "baseline-regression.log", baseline_regression.output)
        if not baseline_regression.ok:
            raise VerificationError(
                "回归测试在修改前未通过，样本环境不干净：\n" + baseline_regression.output[-2000:]
            )

        calls: list[dict[str, Any]] = []
        attempt_diffs: list[dict[str, Any]] = []
        messages = list(base_messages)
        last_target = baseline_target
        last_regression = baseline_regression
        diff_text = ""
        info = None
        success = False

        for attempt in range(1, max_attempts + 1):
            result = client.chat(messages)
            calls.append(
                {
                    "attempt": attempt,
                    "request": {
                        "model": settings.minimax_model,
                        "reasoning_effort": settings.minimax_reasoning_effort,
                        "message_count": len(messages),
                        "user_prompt_chars": sum(len(m["content"]) for m in messages),
                    },
                    "response": result.as_dict(),
                }
            )
            _write(run_dir / "minimax-calls.jsonl", json.dumps(calls[-1], ensure_ascii=False) + "\n", mode="a")
            _write(run_dir / f"minimax-response-{attempt}.txt", result.content)
            try:
                diff_text = extract_unified_diff(result.content)
                diff_text, header_notes = normalize_hunk_headers(diff_text)
                if header_notes:
                    calls[-1]["response"]["hunk_normalization"] = header_notes
                    _write(
                        run_dir / f"attempt-{attempt}.hunk-normalization.json",
                        json.dumps(header_notes, ensure_ascii=False, indent=2),
                    )
                info = validate_diff(diff_text)
            except PatchError as exc:
                _write(run_dir / f"invalid-{attempt}.txt", result.content)
                if attempt == max_attempts:
                    raise PatchError(f"第 {attempt} 次响应不是可用的 unified diff: {exc}") from exc
                messages = base_messages + [
                    {"role": "assistant", "content": result.content},
                    {
                        "role": "user",
                        "content": f"你的响应不是可应用的 unified diff（{exc}）。请重新输出完整 diff，"
                        "只修改 src/ 下的实现文件，并确保 @@ -a,b +c,d @@ 中的行数与正文一致。",
                    },
                ]
                continue

            _write(run_dir / f"attempt-{attempt}.diff", diff_text)
            attempt_diffs.append({"attempt": attempt, "diff": info.as_dict()})
            try:
                apply_diff(diff_text, root, check_only=True)
                apply_diff(diff_text, root)
            except PatchError as exc:
                _write(run_dir / f"invalid-{attempt}.txt", result.content)
                if attempt == max_attempts:
                    raise PatchError(f"第 {attempt} 次响应的补丁无法应用: {exc}") from exc
                messages = base_messages + [
                    {"role": "assistant", "content": result.content},
                    {
                        "role": "user",
                        "content": f"应用补丁失败（{exc}）。请重新输出完整的 unified diff，"
                        "只修改 src/ 下的实现文件，并确保 @@ -a,b +c,d @@ 中的行数与正文一致。",
                    },
                ]
                continue

            target_run = run_pytest(root, target_ids, name=f"attempt-{attempt}.target")
            _write(run_dir / f"attempt-{attempt}-target.log", target_run.output)
            regression_run = run_pytest(root, regression_ids, name=f"attempt-{attempt}.regression")
            _write(run_dir / f"attempt-{attempt}-regression.log", regression_run.output)
            last_target, last_regression = target_run, regression_run

            if target_run.ok and regression_run.ok:
                success = True
                break

            apply_diff(diff_text, root, reverse=True)
            if attempt == max_attempts:
                break
            feedback = [
                "应用上述补丁后测试失败。请基于原始代码重新输出一个完整的 unified diff（不要在上一个补丁上叠加），"
                "确保目标测试与回归测试都通过。",
                "",
                "目标测试结果:",
                target_run.output[-4000:],
                "",
                "回归测试结果:",
                regression_run.output[-3000:],
            ]
            messages = base_messages + [
                {"role": "assistant", "content": result.content},
                {"role": "user", "content": "\n".join(feedback)},
            ]

        _write(
            run_dir / "minimax-calls.jsonl",
            "\n".join(json.dumps(call, ensure_ascii=False) for call in calls) + "\n",
        )

        if not success:
            outcome = ApplyOutcome(
                status="failed",
                run_id=run_id,
                run_dir=str(run_dir),
                task_id=task.id,
                attempts=len(calls),
                summary="MiniMax 补丁未能在限定次数内让目标与回归测试同时通过",
                checks=[
                    {
                        "name": "baseline.target.fails",
                        "status": "passed",
                        "details": f"{baseline_target.failed} failed before change",
                    },
                    {
                        "name": "target.tests",
                        "status": "failed",
                        "details": last_target.output[-1200:],
                    },
                    {
                        "name": "regression.tests",
                        "status": "failed" if not last_regression.ok else "passed",
                        "details": last_regression.output[-800:],
                    },
                ],
                test_runs={
                    "baseline_target": baseline_target.as_dict(str(run_dir / "baseline-target.log")),
                    "baseline_regression": baseline_regression.as_dict(str(run_dir / "baseline-regression.log")),
                    "target": last_target.as_dict(),
                    "regression": last_regression.as_dict(),
                },
                minimax={"model": settings.minimax_model, "calls": len(calls)},
            )
            _record_agent_run(database, project, task, outcome, settings)
            await _record_failure(database, project, task, outcome, settings, store)
            _write(run_dir / "result.json", json.dumps(outcome.as_dict(), ensure_ascii=False, indent=2))
            return outcome

        full_suite = run_pytest(root, [], name="full.suite")
        _write(run_dir / "full-suite.log", full_suite.output)
        if not full_suite.ok:
            apply_diff(diff_text, root, reverse=True)
            outcome = ApplyOutcome(
                status="failed",
                run_id=run_id,
                run_dir=str(run_dir),
                task_id=task.id,
                attempts=len(calls),
                summary="目标与回归测试通过，但全量测试失败，补丁已回滚",
                checks=[
                    {
                        "name": "target.tests",
                        "status": "passed",
                        "details": f"{last_target.passed} passed",
                    },
                    {
                        "name": "regression.tests",
                        "status": "passed",
                        "details": f"{last_regression.passed} passed",
                    },
                    {
                        "name": "full.suite",
                        "status": "failed",
                        "details": full_suite.output[-2000:],
                    },
                ],
                test_runs={
                    "target": last_target.as_dict(),
                    "regression": last_regression.as_dict(),
                    "full_suite": full_suite.as_dict(str(run_dir / "full-suite.log")),
                },
                minimax={"model": settings.minimax_model, "calls": len(calls)},
            )
            _record_agent_run(database, project, task, outcome, settings)
            await _record_failure(database, project, task, outcome, settings, store)
            _write(run_dir / "result.json", json.dumps(outcome.as_dict(), ensure_ascii=False, indent=2))
            return outcome

        # Refresh the seekdb index so a later `context` sees the post-change
        # source and hash instead of the pre-change symbol snapshot.
        import_project(database, project, root)

        patch_path = evidence_root / "patches" / f"{task.id}.patch"
        _write(patch_path, diff_text)

        observations = [
            f"上下文来自 seekdb：{len(context['specs'])} 条规格、{len(context['code'])} 个代码符号、"
            f"{len(target_ids)} 个目标测试、{len(regression_ids)} 个回归测试",
            f"修改前目标测试失败：{baseline_target.failed} failed, {baseline_target.passed} passed",
            f"模型 {settings.minimax_model} 第 {len(calls)} 次尝试返回补丁 {info.paths if info else []}",
            f"修改后目标测试通过：{last_target.passed} passed",
            f"回归测试通过：{last_regression.passed} passed",
            f"全量测试通过：{full_suite.passed} passed",
            "已重新导入 seekdb 索引，后续 context 使用修改后的代码",
        ]
        checks = [
            {
                "name": "baseline.target.fails",
                "status": "passed",
                "details": f"{baseline_target.failed} failed before change",
            },
            {
                "name": "target.tests",
                "status": "passed",
                "details": f"{last_target.passed} passed after change",
            },
            {
                "name": "regression.tests",
                "status": "passed",
                "details": f"{last_regression.passed} passed",
            },
            {
                "name": "full.suite",
                "status": "passed",
                "details": f"{full_suite.passed} passed",
            },
        ]
        outcome = ApplyOutcome(
            status="succeeded",
            run_id=run_id,
            run_dir=str(run_dir),
            task_id=task.id,
            attempts=len(calls),
            diff_path=str(patch_path),
            summary="MiniMax 完成代码修改，目标测试、回归测试与全量测试全部通过",
            checks=checks,
            test_runs={
                "baseline_target": baseline_target.as_dict(str(run_dir / "baseline-target.log")),
                "baseline_regression": baseline_regression.as_dict(str(run_dir / "baseline-regression.log")),
                "target": last_target.as_dict(str(run_dir / f"attempt-{len(calls)}-target.log")),
                "regression": last_regression.as_dict(str(run_dir / f"attempt-{len(calls)}-regression.log")),
                "full_suite": full_suite.as_dict(str(run_dir / "full-suite.log")),
            },
            minimax={"model": settings.minimax_model, "calls": len(calls), "attempts": attempt_diffs},
        )
        receipt = await store.record_outcome(
            task_id=task.id,
            project=project,
            run_id=run_id,
            objective=f"{task.title}：{task.request[:600]}",
            status="succeeded",
            summary=outcome.summary,
            observations=observations,
            checks=checks,
            remaining_work=[],
        )
        _write(run_dir / "powercontext-outcome.json", json.dumps(receipt, ensure_ascii=False, indent=2))
        final_state = await store.snapshot(task.id, project)
        _write(run_dir / "powercontext-state.json", json.dumps(final_state, ensure_ascii=False, indent=2))
        _record_agent_run(database, project, task, outcome, settings)
        _write(run_dir / "result.json", json.dumps(outcome.as_dict(), ensure_ascii=False, indent=2))
        return outcome


async def _record_failure(
    database: Database,
    project: str,
    task: Task,
    outcome: ApplyOutcome,
    settings: Settings,
    store: StateStore,
) -> None:
    await store.record_outcome(
        task_id=task.id,
        project=project,
        run_id=outcome.run_id,
        objective=f"{task.title}：{task.request[:600]}",
        status="failed",
        summary=outcome.summary,
        observations=[
            outcome.summary,
            f"运行证据目录: {outcome.run_dir}",
        ],
        checks=outcome.checks,
        remaining_work=["根据失败日志修正实现后重新运行 specanchor apply"],
    )
    final_state = await store.snapshot(task.id, project)
    _write(Path(outcome.run_dir) / "powercontext-state.json", json.dumps(final_state, ensure_ascii=False, indent=2))


def _record_agent_run(database: Database, project: str, task: Task, outcome: ApplyOutcome, settings: Settings) -> None:
    try:
        with database.session() as session:
            session.execute(
                "INSERT INTO sa_agent_runs (project, task_id, run_id, status, model, patch_path, test_summary, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE status=VALUES(status), test_summary=VALUES(test_summary)",
                (
                    project,
                    task.id,
                    outcome.run_id,
                    outcome.status,
                    settings.minimax_model,
                    outcome.diff_path,
                    outcome.summary,
                    datetime.now(),
                ),
            )
    except Exception:
        # Evidence on disk is authoritative; a bookkeeping failure must not mask
        # the real test result.
        pass
