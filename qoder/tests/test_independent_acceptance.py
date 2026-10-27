"""Independent acceptance checks against real PowerContext, added during review."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi.testclient import TestClient

from backend.powercontext_service import PowerContextService


@asynccontextmanager
async def service_at(path):
    service = PowerContextService(path)
    await service.initialize()
    try:
        yield service
    finally:
        await service.shutdown()


def test_query_cites_the_matched_original_and_native_lineage(tmp_path):
    async def scenario():
        async with service_at(tmp_path) as service:
            project = await service.create_project("实验交接", "独立验收数据")
            pid = project["project_id"]
            original = await service.create_progress(
                pid, "验收报告", "量子传感实验尚缺原始数据", next_steps="补充附件"
            )
            await service.create_progress(pid, "其他记录", "财务报表已归档")
            result = await service.query_handoff(pid, "量子传感")
            assert result["context_items"]
            assert {s["progress_id"] for s in result["sources"]} == {original["progress_id"]}
            citation = result["sources"][0]
            assert citation["source_ref"] == original["source_ref"]
            assert citation["body"] == "量子传感实验尚缺原始数据"
            assert result["prepared_context"]["status"] == "ready"
            assert "量子传感" in result["prepared_context"]["content"]
            hit = result["context_items"][0]
            entry = await service._runtime.records.for_scope(project["scope_id"]).current_memory_entry(
                hit["memory_ref"]["artifact_id"], hit["entry_id"]
            )
            assert any(ref.source_id == original["progress_id"] for ref in entry.sources)

    asyncio.run(scenario())


def test_unmatched_query_does_not_cite_recent_progress(tmp_path):
    async def scenario():
        async with service_at(tmp_path) as service:
            project = await service.create_project("查询边界", "独立验收数据")
            await service.create_progress(project["project_id"], "普通记录", "财务资料已经归档")
            result = await service.query_handoff(project["project_id"], "斑马星云")
            assert result["context_items"] == []
            assert result["sources"] == []
            assert "没有找到" in result["summary"] or "未找到" in result["summary"]

    asyncio.run(scenario())


def test_project_isolation_including_original_sources(tmp_path):
    async def scenario():
        async with service_at(tmp_path) as service:
            a = await service.create_project("项目甲", "隔离验证")
            b = await service.create_project("项目乙", "隔离验证")
            await service.create_progress(a["project_id"], "甲方记录", "量子传感数据")
            result = await service.query_handoff(b["project_id"], "量子传感")
            assert not result["context_items"]
            assert not result["sources"]
            assert not await service.list_progress(b["project_id"])

    asyncio.run(scenario())


def test_default_demo_import_is_idempotent_after_reopen(tmp_path):
    async def scenario():
        async with service_at(tmp_path) as service:
            first = await service.load_demo_data()
            second = await service.load_demo_data()
            assert second["project_id"] == first["project_id"]
            before = len(await service.list_progress(first["project_id"]))
            assert before > 0
            project_count = len(await service.list_projects())
        async with service_at(tmp_path) as service:
            third = await service.load_demo_data()
            assert third["project_id"] == first["project_id"]
            assert len(await service.list_projects()) == project_count
            assert len(await service.list_progress(third["project_id"])) == before

    asyncio.run(scenario())


def test_body_query_and_citation_survive_reopen(tmp_path):
    async def scenario():
        async with service_at(tmp_path) as service:
            project = await service.create_project("持久化验证", "独立验收数据")
            original = await service.create_progress(project["project_id"], "实验记录", "量子传感实验数据")
        async with service_at(tmp_path) as service:
            result = await service.query_handoff(project["project_id"], "量子传感")
            assert result["sources"][0]["source_ref"] == original["source_ref"]
            assert result["context_items"]

    asyncio.run(scenario())


def test_late_old_evaluation_does_not_move_latest_code(tmp_path):
    async def scenario():
        async with service_at(tmp_path) as service:
            project = await service.create_project("版本边界", "独立验收数据")
            pid = project["project_id"]
            await service.create_progress(pid, "最新代码", "已保存代码", branch="feature/latest", commit="a" * 40, record_kind="code")
            await service.create_progress(pid, "补录旧版评测", "历史评测", branch="feature/old", commit="b" * 40, evaluation_result="评测完成", record_kind="evaluation")
            state = await service.get_version_status(pid)
            assert state["latest_code"]["commit"] == "a" * 40
            assert state["latest_evaluation"]["commit"] == "b" * 40
            assert state["has_unevaluated_updates"]

    asyncio.run(scenario())


def test_new_code_without_evaluation_is_flagged(tmp_path):
    async def scenario():
        async with service_at(tmp_path) as service:
            project = await service.create_project("尚未评测", "独立验收数据")
            await service.create_progress(project["project_id"], "代码提交", "已提交待评测", branch="dev", commit="c" * 40, record_kind="code")
            state = await service.get_version_status(project["project_id"])
            assert state["latest_evaluation"] is None
            assert state["has_unevaluated_updates"]

    asyncio.run(scenario())


def test_same_commit_different_branch_is_not_same_evaluation(tmp_path):
    async def scenario():
        async with service_at(tmp_path) as service:
            project = await service.create_project("分支边界", "独立验收数据")
            pid = project["project_id"]
            await service.create_progress(pid, "代码", "代码", branch="alpha", commit="d" * 40, record_kind="code")
            await service.create_progress(pid, "评测", "评测", branch="beta", commit="d" * 40, evaluation_result="通过", record_kind="evaluation")
            state = await service.get_version_status(pid)
            assert state["has_unevaluated_updates"]
            assert state["branch_differs"]

    asyncio.run(scenario())


def test_persisted_timestamps_have_explicit_timezone(tmp_path):
    async def scenario():
        async with service_at(tmp_path) as service:
            project = await service.create_project("时间验证", "独立验收数据")
            assert datetime.fromisoformat(project["created_at"].replace("Z", "+00:00")).utcoffset() is not None
            result = await service.create_progress(project["project_id"], "时间记录", "核验时间戳")
            assert datetime.fromisoformat(result["recorded_at"].replace("Z", "+00:00")).utcoffset() is not None

    asyncio.run(scenario())


def test_http_empty_input_and_missing_project_errors(tmp_path, monkeypatch):
    from backend.main import app

    monkeypatch.setenv("RELAYDESK_DATA_DIR", str(tmp_path))
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post("/api/projects", json={"name": "   "}).status_code == 422
        assert client.post("/api/handoff/query", json={"project_id": "missing", "question": " "}).status_code == 422
        assert client.get("/api/projects/missing").status_code == 404
        assert client.post("/api/handoff/query", json={"project_id": "missing", "question": "数据"}).status_code == 404


def test_http_native_citations_and_static_assets(tmp_path, monkeypatch):
    from backend.main import app

    monkeypatch.setenv("RELAYDESK_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "HTTP 验收", "description": "独立验收数据"}).json()
        response = client.post("/api/progress", json={"project_id": project["project_id"], "title": "报告", "body": "量子传感实验数据"})
        assert response.status_code == 200
        original = response.json()
        result = client.post("/api/handoff/query", json={"project_id": project["project_id"], "question": "量子传感"})
        assert result.status_code == 200
        assert result.json()["sources"][0]["source_ref"] == original["source_ref"]
        for path in ("/", "/static/app.js", "/static/style.css"):
            assert client.get(path).status_code == 200


def test_http_service_failure_is_not_an_empty_success(tmp_path, monkeypatch):
    from backend.main import app

    async def fail_query(self, project_id, question):
        raise RuntimeError("验收注入的存储服务故障")

    monkeypatch.setenv("RELAYDESK_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(PowerContextService, "query_handoff", fail_query)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/handoff/query", json={"project_id": "missing", "question": "数据"})
        assert response.status_code == 503
        assert "detail" in response.json()
