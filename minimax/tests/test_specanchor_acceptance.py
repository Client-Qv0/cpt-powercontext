"""Acceptance tests for the SpecAnchor context module itself.

They exercise the real integrations required by the task: seekdb retrieval drives
the selected sources, and PowerContext stores/reuses task state across runtime
instances.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import shutil
import uuid
from pathlib import Path

import pytest

from specanchor.config import PACKAGE_ROOT, Settings
from specanchor.db import Database
from specanchor.ingest import import_project
from specanchor.retrieve import ContextBuilder, Task
from specanchor.state import StateStore

TASK = PACKAGE_ROOT / "examples" / "task-book-filters.json"
SAMPLE = PACKAGE_ROOT / "sample_project"
IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", "pytest-cache-files-*")


def empty_state() -> dict:
    return {
        "provider": "PowerContext (test, empty)",
        "scope_id": None,
        "task_id": "TASK-BOOK-0042",
        "contract": None,
        "latest_outcome": None,
        "done": [],
        "todo": [],
        "verification": [],
        "events": [],
        "event_count": 0,
    }


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings.load()


@pytest.fixture(scope="session")
def database(settings: Settings) -> Database:
    db = Database(settings)
    db.init_schema()
    return db


def workdir(name: str) -> Path:
    base = PACKAGE_ROOT / ".state" / "test-tmp"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{name}-{uuid.uuid4().hex[:8]}"


@pytest.fixture()
def project():
    name = f"test_{uuid.uuid4().hex[:10]}"
    root = workdir("project")
    shutil.copytree(SAMPLE, root, ignore=IGNORE)
    yield name, root
    shutil.rmtree(root, ignore_errors=True)


def test_context_selects_required_sources(database: Database, project) -> None:
    name, root = project
    import_project(database, name, root)
    context = ContextBuilder(database, name, root).build(Task.load(TASK), empty_state())

    spec_ids = {item["spec_id"] for item in context["specs"]}
    assert {"BOOK-004", "BOOK-005", "API-001"} <= spec_ids
    assert {"BOOK-001", "BOOK-002", "BOOK-003"} <= spec_ids

    code_symbols = {item["qualname"] for item in context["code"]}
    assert "CatalogService.list_books" in code_symbols
    assert any(item["path"] == "src/booknest/catalog.py" for item in context["code"])
    assert not any(item["path"].endswith("reports.py") for item in context["code"])

    target = context["tests"]["target"]
    regression = context["tests"]["regression"]
    assert len(target) == 8
    assert all(item["path"].endswith("test_catalog_filters.py") for item in target)
    assert {item["path"] for item in regression} == {
        "tests/test_api_contract.py",
        "tests/test_catalog_contract.py",
        "tests/test_pagination.py",
    }
    assert not ({item["test_id"] for item in target} & {item["test_id"] for item in regression})


def test_every_selected_source_exists_and_matches_digest(database: Database, project) -> None:
    name, root = project
    import_project(database, name, root)
    context = ContextBuilder(database, name, root).build(Task.load(TASK), empty_state())

    assert context["sources"]
    for source in context["sources"]:
        path = root / source["path"]
        assert source["exists"] is True
        assert path.is_file()
        assert source["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_context_is_derived_from_database_queries(database: Database, project) -> None:
    name, root = project
    import_project(database, name, root)
    context = ContextBuilder(database, name, root).build(Task.load(TASK), empty_state())

    db = context["diagnostics"]["db"]
    assert db["database"]
    assert len(db["queries"]) >= 5
    assert any("sa_terms" in query["sql"] for query in db["queries"])
    assert any("sa_spec_sections" in query["sql"] for query in db["queries"])
    assert any("sa_tests" in query["sql"] for query in db["queries"])


def test_spec_update_is_used_after_reimport(database: Database, project) -> None:
    name, root = project
    task = Task.load(TASK)
    first = import_project(database, name, root)
    before = ContextBuilder(database, name, root).build(task, empty_state())
    before_section = next(item for item in before["specs"] if item["spec_id"] == "BOOK-004")
    assert "NFC" not in before_section["text"]

    replacement = PACKAGE_ROOT / "examples" / "spec-update" / "catalog-v4.md"
    (root / "specs" / "catalog.md").write_text(replacement.read_text(encoding="utf-8"), encoding="utf-8")
    second = import_project(database, name, root)
    after = ContextBuilder(database, name, root).build(task, empty_state())
    after_section = next(item for item in after["specs"] if item["spec_id"] == "BOOK-004")

    assert first.specs < second.specs
    assert second.changed_sections and second.changed_sections[0]["spec_id"] == "BOOK-004"
    assert after_section["revision"] == 2
    assert after_section["content_hash"] != before_section["content_hash"]
    assert "NFC" in after_section["text"]
    assert "v3 新增需求" not in after_section["text"]
    assert after["context_digest"] != before["context_digest"]

    with database.session() as session:
        active = session.fetchone(
            "SELECT COUNT(*) AS n FROM sa_spec_sections "
            "WHERE project=%s AND spec_id='BOOK-004' AND active=1",
            (name,),
        )
        stale = session.fetchone(
            "SELECT COUNT(*) AS n FROM sa_spec_sections "
            "WHERE project=%s AND spec_id='BOOK-004' AND active=0",
            (name,),
        )
    assert active["n"] == 1
    assert stale["n"] == 1


def test_powercontext_state_survives_restart(settings: Settings) -> None:
    state_dir = workdir("pc-state")
    local = dataclasses.replace(settings, state_dir=state_dir)
    project = f"state_{uuid.uuid4().hex[:8]}"

    async def write_phase() -> dict:
        async with StateStore(local) as store:
            snapshot = await store.snapshot("TASK-BOOK-0042", project)
            assert snapshot["done"] == [] and snapshot["todo"] == [] and snapshot["verification"] == []
            contract = await store.ensure_contract(
                task_id="TASK-BOOK-0042",
                project=project,
                objective="add topic/available filters",
                in_scope=["src/booknest/catalog.py"],
                completion_criteria=["target tests pass", "regression tests pass"],
            )
            assert contract["created"] is True
            receipt = await store.record_outcome(
                task_id="TASK-BOOK-0042",
                project=project,
                run_id="run-test",
                objective="add topic/available filters",
                status="partial",
                summary="context built",
                observations=["context built from seekdb"],
                checks=[{"name": "baseline", "status": "failed", "details": "\n  8 failed  \n"}],
                remaining_work=["apply the patch"],
            )
            assert receipt["source_ref"]["source_id"].startswith("outcome:")
            return await store.snapshot("TASK-BOOK-0042", project)

    first = asyncio.run(write_phase())
    assert first["done"] == ["context built from seekdb"]
    assert first["todo"] == ["apply the patch"]
    assert first["verification"][0]["status"] == "failed"
    assert first["verification"][0]["details"] == "8 failed"

    async def read_phase() -> dict:
        async with StateStore(local) as store:
            return await store.snapshot("TASK-BOOK-0042", project)

    second = asyncio.run(read_phase())
    assert second["scope_id"] == first["scope_id"]
    assert second["done"] == first["done"]
    assert second["todo"] == first["todo"]
    assert second["verification"] == first["verification"]
    assert second["event_count"] == 2
    assert state_dir.joinpath("powercontext.db").is_file()
    shutil.rmtree(state_dir, ignore_errors=True)


def test_task_file_schema_is_required() -> None:
    broken = workdir("task") / "task.json"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text(json.dumps({"id": "x"}), encoding="utf-8")
    with pytest.raises(Exception):
        Task.load(broken)
    shutil.rmtree(broken.parent, ignore_errors=True)


@pytest.mark.parametrize("change", ["spec", "code", "test", "fixture", "add", "delete"])
def test_unimported_changes_rejected(database: Database, project, change) -> None:
    name, root = project
    import_project(database, name, root)
    paths = {"spec": "specs/catalog.md", "code": "src/booknest/catalog.py",
             "test": "tests/test_catalog_filters.py", "fixture": "tests/conftest.py",
             "delete": "specs/reports.md"}
    if change == "add":
        (root / "src/booknest/new_module.py").write_text("value = 1\n", encoding="utf-8")
    elif change == "delete":
        (root / paths[change]).unlink()
    else:
        path = root / paths[change]
        path.write_text(path.read_text(encoding="utf-8") + "\n# unimported change\n", encoding="utf-8")
    from specanchor.errors import SpecAnchorError
    with pytest.raises(SpecAnchorError, match="ingest"):
        ContextBuilder(database, name, root).build(Task.load(TASK), empty_state())
    import_project(database, name, root)
    assert ContextBuilder(database, name, root).build(Task.load(TASK), empty_state())["sources"]
