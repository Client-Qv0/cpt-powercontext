"""Independent proof that the change is effective.

1. Extract the committed ``sample_project`` baseline snapshot.
2. Run the *target* tests selected by SpecAnchor -> they must fail for a real
   functional reason (exit 1, at least one failed assertion), and the selected
   regression tests must pass.
3. Copy the current (post-MiniMax) sample project and run the same target and
   regression tests plus the full suite -> everything must pass.

The script writes command/exit-code logs under ``evidence/test-logs/`` and a
machine-readable summary under ``evidence/verify-change.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from specanchor.agent import run_pytest  # noqa: E402
from specanchor.config import Settings  # noqa: E402
from specanchor.db import Database  # noqa: E402
from specanchor.ingest import import_project  # noqa: E402
from specanchor.retrieve import ContextBuilder, Task  # noqa: E402

IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", "pytest-cache-files-*")


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in {"__pycache__", ".pytest_cache"} for part in path.relative_to(root).parts):
            continue
        if path.name.startswith("pytest-cache-files-"):
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def extract_baseline(zip_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = destination / member.filename
            resolved = target.resolve()
            if destination.resolve() not in resolved.parents and resolved != destination.resolve():
                raise SystemExit(f"unsafe path in baseline zip: {member.filename}")
        archive.extractall(destination)


def write_log(path: Path, *, title: str, command: list[str], cwd: Path, run, code_version: str) -> None:
    header = [
        f"# {title}",
        f"# timestamp: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"# command: {' '.join(command)}",
        f"# cwd: {cwd}",
        f"# code_version: {code_version}",
        f"# exit_code: {run.exit_code}",
        f"# passed: {run.passed}  failed: {run.failed}  errors: {run.errors}",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(header) + run.output, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="验证目标测试修改前失败、修改后通过")
    parser.add_argument("--task", default=str(PACKAGE_ROOT / "examples" / "task-book-filters.json"))
    parser.add_argument("--baseline", default=str(PACKAGE_ROOT / "evidence" / "baseline" / "sample_project.zip"))
    parser.add_argument("--final", default=str(PACKAGE_ROOT / "sample_project"))
    parser.add_argument("--logs", default=str(PACKAGE_ROOT / "evidence" / "test-logs"))
    parser.add_argument("--summary", default=str(PACKAGE_ROOT / "evidence" / "verify-change.json"))
    args = parser.parse_args()

    settings = Settings.load()
    task = Task.load(Path(args.task))
    baseline_zip = Path(args.baseline)
    final_root = Path(args.final)

    database = Database(settings)
    import_project(database, task.project, final_root)
    empty_state = {
        "provider": "PowerContext (not used by this verifier)",
        "scope_id": None,
        "done": [],
        "todo": [],
        "verification": [],
        "events": [],
    }
    context = ContextBuilder(database, task.project, final_root).build(task, empty_state)
    target_ids = [item["path"] + "::" + "::".join(item["test_id"].split(".")) for item in context["tests"]["target"]]
    regression_ids = [item["path"] + "::" + "::".join(item["test_id"].split(".")) for item in context["tests"]["regression"]]

    work = PACKAGE_ROOT / ".state" / "verify" / f"run-{uuid.uuid4().hex[:8]}"
    work.mkdir(parents=True, exist_ok=True)
    baseline_root = work / "baseline"
    after_root = work / "after"
    baseline_root.mkdir()
    extract_baseline(baseline_zip, baseline_root)
    shutil.copytree(final_root, after_root, ignore=IGNORE)

    code_version = {
        "baseline": tree_digest(baseline_root),
        "after": tree_digest(after_root),
        "git_head": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(PACKAGE_ROOT), capture_output=True, text=True
        ).stdout.strip()
        or "not-a-git-checkout",
    }

    checks: list[dict[str, object]] = []
    logs = Path(args.logs)

    def record(name: str, run, expectation: str, passed: bool) -> None:
        checks.append(
            {
                "name": name,
                "exit_code": run.exit_code,
                "passed": run.passed,
                "failed": run.failed,
                "errors": run.errors,
                "expectation": expectation,
                "ok": passed,
            }
        )

    baseline_target = run_pytest(baseline_root, target_ids, name="baseline.target")
    write_log(
        logs / "before-target.log",
        title="修改前：目标功能测试（预期失败）",
        command=[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *target_ids],
        cwd=baseline_root,
        run=baseline_target,
        code_version=code_version["baseline"],
    )
    baseline_ok = (
        baseline_target.exit_code == 1
        and baseline_target.failed > 0
        and not baseline_target.environment_error
    )
    record("before.target", baseline_target, "exit=1 且存在真实断言失败", baseline_ok)

    baseline_regression = run_pytest(baseline_root, regression_ids, name="baseline.regression")
    write_log(
        logs / "before-regression.log",
        title="修改前：回归测试（预期通过）",
        command=[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *regression_ids],
        cwd=baseline_root,
        run=baseline_regression,
        code_version=code_version["baseline"],
    )
    record("before.regression", baseline_regression, "exit=0", baseline_regression.ok)

    after_target = run_pytest(after_root, target_ids, name="after.target")
    write_log(
        logs / "after-target.log",
        title="修改后：目标功能测试（预期通过）",
        command=[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *target_ids],
        cwd=after_root,
        run=after_target,
        code_version=code_version["after"],
    )
    record("after.target", after_target, "exit=0", after_target.ok)

    after_regression = run_pytest(after_root, regression_ids, name="after.regression")
    write_log(
        logs / "after-regression.log",
        title="修改后：回归测试（预期通过）",
        command=[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *regression_ids],
        cwd=after_root,
        run=after_regression,
        code_version=code_version["after"],
    )
    record("after.regression", after_regression, "exit=0", after_regression.ok)

    after_full = run_pytest(after_root, [], name="after.full")
    write_log(
        logs / "after-full.log",
        title="修改后：全量测试（预期通过）",
        command=[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=after_root,
        run=after_full,
        code_version=code_version["after"],
    )
    record("after.full", after_full, "exit=0", after_full.ok)

    summary = {
        "task": task.id,
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "code_version": code_version,
        "target_test_count": len(target_ids),
        "regression_test_count": len(regression_ids),
        "checks": checks,
        "ok": all(item["ok"] for item in checks),
        "sample_root": str(final_root),
        "baseline_zip": str(baseline_zip),
    }
    summary_path = Path(args.summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    shutil.rmtree(work, ignore_errors=True)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
