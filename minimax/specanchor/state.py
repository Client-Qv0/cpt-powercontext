"""Task state persisted and reused through PowerContext.

PowerContext's built-in Work loop is used directly:

* ``WorkContract``  — the task objective, scope and completion criteria.
* ``TaskOutcome``   — the progress, verification checks and remaining work.
* ``continuity()``  — the durable, ordered timeline read back by a later run.

Both records are captured as PowerContext Sources in a project Scope.  The
module is deliberately run as a fresh CLI process each time, so the demo also
demonstrates cross-process (restart) reuse rather than an in-memory cache.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from powercontext.builtin.runtime import BuiltinConfig, open_builtin_runtime
from powercontext.builtin.scope import ScopeDraft
from powercontext.builtin.work import (
    CreateWorkContract,
    RecordTaskOutcome,
    TaskCheck,
    TaskOutcome,
    WorkClaim,
    WorkContract,
)

from .config import Settings
from .errors import StateError


def _sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


class StateStore:
    """Async context manager around one PowerContext built-in runtime."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._context = None
        self.runtime = None
        self.scope_id: str | None = None

    async def __aenter__(self) -> "StateStore":
        self.settings.state_dir.mkdir(parents=True, exist_ok=True)
        config = BuiltinConfig(
            database={"kind": "sqlite", "url": _sqlite_url(self.settings.powercontext_db)}
        )
        self._context = open_builtin_runtime(
            config,
            scheduler_path=self.settings.state_dir / "powercontext.scheduler.db",
        )
        try:
            self.runtime = await self._context.__aenter__()
        except Exception as exc:  # pragma: no cover - local runtime failure
            raise StateError(f"PowerContext 启动失败: {exc}") from exc
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._context is not None:
            await self._context.__aexit__(exc_type, exc, tb)

    async def scope(self, project: str) -> str:
        if self.scope_id is not None:
            return self.scope_id
        draft = ScopeDraft(
            title=f"SpecAnchor · {project}",
            summary="SDD 任务上下文、代码修改与验证记录（SpecAnchor 自动创建）",
            idempotency_key=f"specanchor:scope:{project}",
        )
        try:
            descriptor = await self.runtime.scopes.create(draft)
        except Exception as exc:  # pragma: no cover - local runtime failure
            raise StateError(f"PowerContext Scope 创建失败: {exc}") from exc
        self.scope_id = descriptor.scope_id
        return self.scope_id

    async def _records(self, project: str):
        return self.runtime.records.for_scope(await self.scope(project))

    async def _work(self, project: str):
        return self.runtime.work.for_scope(await self.scope(project))

    async def snapshot(self, task_id: str, project: str) -> dict[str, Any]:
        scope_id = await self.scope(project)
        work = await self._work(project)
        records = await self._records(project)
        try:
            continuity = await work.continuity()
        except Exception as exc:  # pragma: no cover - local runtime failure
            raise StateError(f"PowerContext 状态读取失败: {exc}") from exc

        events: list[dict[str, Any]] = []
        contract: dict[str, Any] | None = None
        latest_outcome: dict[str, Any] | None = None
        for event in continuity.events:
            source_id = event.source_ref.source_id
            record = await records.get_source(event.source_ref.source_type, source_id)
            try:
                payload = json.loads(record.content)
            except (TypeError, ValueError):
                payload = {}
            item = {
                "position": event.position,
                "kind": event.kind,
                "status": event.status,
                "summary": event.summary,
                "source_ref": {"source_type": event.source_ref.source_type, "source_id": source_id},
                "captured_at": payload.get("captured_at"),
                "record": payload,
            }
            events.append(item)
            if event.kind == "work-contract" and source_id == f"contract:{task_id}":
                contract = item
            elif event.kind == "task-outcome" and source_id.startswith(f"outcome:{task_id}:"):
                latest_outcome = item

        done, todo, verification = _project_state(contract, latest_outcome)
        return {
            "provider": "PowerContext 1.4.1 builtin runtime (Work contract / Task outcome)",
            "scope_id": scope_id,
            "task_id": task_id,
            "storage": str(self.settings.powercontext_db),
            "contract": contract,
            "latest_outcome": latest_outcome,
            "done": done,
            "todo": todo,
            "verification": verification,
            "events": events,
            "event_count": continuity.total_event_count,
        }

    async def ensure_contract(
        self,
        *,
        task_id: str,
        project: str,
        objective: str,
        in_scope: list[str],
        completion_criteria: list[str],
    ) -> dict[str, Any]:
        scope_id = await self.scope(project)
        work = await self._work(project)
        source_id = f"contract:{task_id}"
        continuity = await work.continuity()
        for event in continuity.events:
            if event.kind == "work-contract" and event.source_ref.source_id == source_id:
                return {
                    "created": False,
                    "scope_id": scope_id,
                    "source_ref": {"source_type": event.source_ref.source_type, "source_id": source_id},
                    "position": event.position,
                }
        contract = WorkContract(
            objective=objective,
            facts=(
                WorkClaim(text="任务状态由 SpecAnchor 通过 PowerContext Work contract 保存。"),
                WorkClaim(text="上下文中的规格、代码与测试来源均来自 seekdb 索引且已校验存在。"),
            ),
            in_scope=tuple(in_scope) or ("sample_project",),
            completion_criteria=tuple(completion_criteria),
            authorization_notes=("仅允许修改 src/ 下的实现文件，不得修改测试与规格。",),
        )
        try:
            receipt = await work.create_contract(CreateWorkContract(source_id=source_id, contract=contract))
        except Exception as exc:  # pragma: no cover - local runtime failure
            raise StateError(f"PowerContext 任务契约保存失败: {exc}") from exc
        return {
            "created": True,
            "scope_id": scope_id,
            "source_ref": {
                "source_type": receipt.source_ref.source_type,
                "source_id": receipt.source_ref.source_id,
            },
            "position": receipt.position,
            "digest": receipt.content_digest,
        }

    async def record_outcome(
        self,
        *,
        task_id: str,
        project: str,
        run_id: str,
        objective: str,
        status: str,
        summary: str,
        observations: list[str],
        checks: list[dict[str, str]],
        remaining_work: list[str],
    ) -> dict[str, Any]:
        scope_id = await self.scope(project)
        work = await self._work(project)
        source_id = f"outcome:{task_id}:{run_id}"
        task_checks = tuple(
            TaskCheck(name=check["name"], status=check["status"], details=check.get("details"))
            for check in checks
        )
        outcome = TaskOutcome(
            objective=objective,
            status=status,
            summary=summary,
            observations=tuple(WorkClaim(text=text) for text in observations),
            checks=task_checks,
            remaining_work=tuple(remaining_work),
        )
        try:
            receipt = await work.record_outcome(RecordTaskOutcome(source_id=source_id, outcome=outcome))
        except Exception as exc:  # pragma: no cover - local runtime failure
            raise StateError(f"PowerContext 任务结果保存失败: {exc}") from exc
        return {
            "scope_id": scope_id,
            "source_ref": {
                "source_type": receipt.source_ref.source_type,
                "source_id": receipt.source_ref.source_id,
            },
            "position": receipt.position,
            "digest": receipt.content_digest,
            "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }


def _project_state(
    contract: dict[str, Any] | None, outcome: dict[str, Any] | None
) -> tuple[list[str], list[str], list[dict[str, str]]]:
    done: list[str] = []
    todo: list[str] = []
    verification: list[dict[str, str]] = []

    if contract is not None:
        criteria = contract["record"].get("completion_criteria", [])
        todo.extend(str(item) for item in criteria)

    if outcome is not None:
        payload = outcome["record"]
        done.extend(str(item.get("text", "")) for item in payload.get("observations", []) if item.get("text"))
        for check in payload.get("checks", []):
            verification.append(
                {
                    "name": str(check.get("name", "")),
                    "status": str(check.get("status", "")),
                    "details": str(check.get("details") or ""),
                }
            )
            if check.get("status") == "passed" and check.get("name"):
                done.append(f"验证通过: {check['name']}")
        remaining = [str(item) for item in payload.get("remaining_work", []) if str(item).strip()]
        if remaining:
            todo = remaining
        elif payload.get("status") in {"succeeded", "partial"}:
            todo = []
    return _dedupe(done), _dedupe(todo), verification


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def reset_state(settings: Settings) -> list[str]:
    """Remove the local PowerContext database (a clean, repeatable start)."""

    removed: list[str] = []
    for name in ("powercontext.db", "powercontext.db-wal", "powercontext.db-shm", "powercontext.scheduler.db"):
        path = settings.state_dir / name
        if path.exists():
            path.unlink()
            removed.append(str(path))
    return removed
