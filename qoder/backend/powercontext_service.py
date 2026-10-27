"""PowerContext service layer for RelayDesk using VERIFIED deterministic workflow.

This module implements the native Source lineage workflow:
1. Custom candidate_pipeline extracts MemoryEntryInput from ContentSource
2. capture() sources with metadata
3. flush() to process sources into memory with native SourceRef lineage
4. search() returns hits with actual source citations
5. current_memory_entry().sources provides traceable SourceRef
6. get_source() retrieves original content

NO explicit remember() with fabricated sources.
NO recent-progress pretending to be citations.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from powercontext.builtin.artifacts.memory import MemoryCandidateRequest, MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    PrepareContextRequest,
    SearchMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft, ScopeIdempotencyConflictError
from powercontext.builtin.sources import ContentSource

logger = logging.getLogger(__name__)


class ProjectNotFoundError(ValueError):
    """The requested application project does not exist."""

# Stable demo project identity
DEMO_PROJECT_IDEMPOTENCY_KEY = "relaydesk.demo-project.v1"
DEMO_PROJECT_NAME = "示例团队项目"
DEMO_PROJECT_DESCRIPTION = "这是一个用于演示的虚构项目，展示 RelayDesk 的核心功能。所有数据均为样例，不代表真实评测结果。"


class ProgressContentPipeline:
    """Deterministic progress-content extraction adapter.

    Extracts MemoryEntryInput from ContentSource with metadata.type='progress'.
    This is a non-LLM deterministic adapter that preserves native Source lineage.
    """

    async def extract(self, request: MemoryCandidateRequest, /) -> tuple[MemoryEntryInput, ...]:
        """Extract memory entries from captured progress sources.

        Args:
            request: Memory candidate request containing sources

        Returns:
            Tuple of MemoryEntryInput with native source linkage
        """
        entries = []
        for source in request.sources:
            if isinstance(source, ContentSource) and source.metadata.get("type") == "progress":
                try:
                    # Parse the progress data
                    progress_data = json.loads(source.content)

                    # Build comprehensive memory text including all fields
                    memory_parts = [f"项目进展: {progress_data.get('title', '')}"]

                    if progress_data.get('body'):
                        memory_parts.append(f"详情: {progress_data['body']}")

                    if progress_data.get('status'):
                        memory_parts.append(f"状态: {progress_data['status']}")

                    if progress_data.get('owner'):
                        memory_parts.append(f"负责人: {progress_data['owner']}")

                    if progress_data.get('next_steps'):
                        memory_parts.append(f"下一步: {progress_data['next_steps']}")

                    if progress_data.get('branch'):
                        memory_parts.append(f"分支: {progress_data['branch']}")

                    if progress_data.get('commit'):
                        memory_parts.append(f"Commit: {progress_data['commit']}")

                    if progress_data.get('evaluation_result'):
                        memory_parts.append(f"评测: {progress_data['evaluation_result']}")

                    memory_text = "。".join(memory_parts) + "。"

                    # Create MemoryEntryInput with NATIVE source linkage
                    entries.append(
                        MemoryEntryInput(
                            kind="fact",
                            text=memory_text,
                            sources=(source,),  # Native SourceRef lineage
                        )
                    )
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"Failed to parse progress source: {e}")
                    continue

        return tuple(entries)


class PowerContextService:
    """Service layer for PowerContext operations using VERIFIED deterministic workflow."""

    def __init__(self, data_dir: Path):
        """Initialize the service.

        Args:
            data_dir: Directory for SQLite database
        """
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "relaydesk.db"
        self.db_url = f"sqlite+aiosqlite:///{self.db_path}"
        self.config = BuiltinConfig(database=SQLiteConfig(url=self.db_url))
        self._runtime_context = None
        self._runtime = None
        self._initialized = False

    async def initialize(self):
        """Initialize PowerContext builtin runtime with deterministic pipeline."""
        if self._initialized:
            return

        logger.info(f"Opening PowerContext builtin runtime at {self.db_path}")

        # Use VERIFIED deterministic candidate_pipeline
        pipeline = ProgressContentPipeline()
        self._runtime_context = open_builtin_runtime(self.config, candidate_pipeline=pipeline)
        self._runtime = await self._runtime_context.__aenter__()
        self._initialized = True
        logger.info("PowerContext runtime initialized with deterministic pipeline")

    async def shutdown(self):
        """Shutdown the runtime."""
        if self._runtime_context:
            await self._runtime_context.__aexit__(None, None, None)
            self._runtime_context = None
            self._runtime = None
        self._initialized = False

    def _require_runtime(self):
        """Ensure runtime is initialized."""
        if not self._initialized or not self._runtime:
            raise RuntimeError("PowerContext runtime not initialized")
        return self._runtime

    async def create_project(self, name: str, description: str) -> dict[str, Any]:
        """Create a new project as a PowerContext scope.

        Args:
            name: Project name (must be non-empty)
            description: Project description

        Returns:
            Project metadata with ID

        Raises:
            ValueError: If name is empty
        """
        if not name or not name.strip():
            raise ValueError("Project name cannot be empty")

        runtime = self._require_runtime()
        project_id = f"proj-{uuid4().hex[:12]}"
        idempotency_key = f"relaydesk.project.{project_id}"

        # Create scope for the project
        scope = await runtime.scopes.create(
            ScopeDraft(
                title=name.strip(),
                summary=description.strip() if description else "",
                idempotency_key=idempotency_key,
            )
        )

        # Store project metadata as a source
        project_data = {
            "type": "project",
            "project_id": project_id,
            "scope_id": scope.scope_id,
            "name": name.strip(),
            "description": description.strip() if description else "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        await runtime.sources.for_scope(scope.scope_id).capture(
            CaptureSource(
                source_id=f"project-meta-{project_id}",
                content=json.dumps(project_data, ensure_ascii=False),
                metadata={"project_id": project_id, "type": "project"},
            )
        )

        return {
            "project_id": project_id,
            "scope_id": scope.scope_id,
            "name": name.strip(),
            "description": description.strip() if description else "",
            "created_at": project_data["created_at"],
        }

    async def list_projects(self) -> list[dict[str, Any]]:
        """List all projects with cursor-based pagination.

        Returns:
            List of project metadata
        """
        runtime = self._require_runtime()
        projects = []

        # List all scopes
        scopes = await runtime.scopes.list()

        for scope in scopes:
            # Paginate through sources to find project metadata
            cursor = None
            while True:
                sources_page = await runtime.records.for_scope(scope.scope_id).list_sources(
                    limit=100, cursor=cursor
                )

                for source in sources_page.items:
                    try:
                        data = json.loads(source.content)
                        if data.get("type") == "project":
                            projects.append({
                                "project_id": data["project_id"],
                                "scope_id": scope.scope_id,
                                "name": data["name"],
                                "description": data.get("description", ""),
                                "created_at": data.get("created_at"),
                            })
                            break  # Found project metadata, move to next scope
                    except (json.JSONDecodeError, KeyError):
                        continue
                else:
                    # No project metadata found in this page
                    if sources_page.next_cursor:
                        cursor = sources_page.next_cursor
                        continue
                    break  # No more pages

                break  # Found project metadata, move to next scope

        return projects

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        """Get project details.

        Args:
            project_id: Project ID

        Returns:
            Project metadata or None
        """
        if not project_id or not project_id.strip():
            raise ValueError("Project ID cannot be empty")

        runtime = self._require_runtime()

        # List all scopes and find the one with matching project_id
        scopes = await runtime.scopes.list()

        for scope in scopes:
            cursor = None
            while True:
                sources_page = await runtime.records.for_scope(scope.scope_id).list_sources(
                    limit=100, cursor=cursor
                )

                for source in sources_page.items:
                    try:
                        data = json.loads(source.content)
                        if data.get("type") == "project" and data.get("project_id") == project_id:
                            return {
                                "project_id": data["project_id"],
                                "scope_id": scope.scope_id,
                                "name": data["name"],
                                "description": data.get("description", ""),
                                "created_at": data.get("created_at"),
                            }
                    except (json.JSONDecodeError, KeyError):
                        continue

                if sources_page.next_cursor:
                    cursor = sources_page.next_cursor
                else:
                    break

        return None

    async def create_progress(
        self,
        project_id: str,
        title: str,
        body: str,
        owner: str | None = None,
        status: str = "进行中",
        next_steps: str = "",
        branch: str | None = None,
        commit: str | None = None,
        evaluation_result: str | None = None,
        record_kind: str = "progress",
    ) -> dict[str, Any]:
        """Create a progress record as a PowerContext source.

        Args:
            project_id: Project ID
            title: Progress title (must be non-empty)
            body: Progress details (must be non-empty)
            owner: Responsible person (optional)
            status: Status label
            next_steps: Next steps
            branch: Code branch (optional)
            commit: Commit hash (optional, must be valid if provided)
            evaluation_result: Evaluation result (optional)
            record_kind: Type of record (progress/code/evaluation)

        Returns:
            Progress record metadata

        Raises:
            ValueError: If required fields are empty or invalid
        """
        if not project_id or not project_id.strip():
            raise ValueError("Project ID cannot be empty")
        if not title or not title.strip():
            raise ValueError("Title cannot be empty")
        if not body or not body.strip():
            raise ValueError("Body cannot be empty")

        # Validate commit format if provided
        if commit and not commit.strip():
            raise ValueError("Commit cannot be empty if provided")
        if commit and len(commit.strip()) < 7:
            raise ValueError("Commit hash must be at least 7 characters")

        # Validate status
        valid_statuses = {"进行中", "已完成", "待处理", "已阻塞"}
        if status not in valid_statuses:
            raise ValueError(f"Invalid status: {status}. Must be one of {valid_statuses}")

        # Validate record_kind
        valid_kinds = {"progress", "code", "evaluation"}
        if record_kind not in valid_kinds:
            raise ValueError(f"Invalid record_kind: {record_kind}. Must be one of {valid_kinds}")

        runtime = self._require_runtime()

        # Find the scope for this project
        project = await self.get_project(project_id)
        if not project:
            raise ProjectNotFoundError(f"Project {project_id} not found")

        scope_id = project["scope_id"]
        progress_id = f"prog-{uuid4().hex[:12]}"
        recorded_at = datetime.now(timezone.utc).isoformat()

        progress_data = {
            "type": "progress",
            "record_kind": record_kind,
            "progress_id": progress_id,
            "project_id": project_id,
            "title": title.strip(),
            "body": body.strip(),
            "owner": owner.strip() if owner else None,
            "status": status,
            "next_steps": next_steps.strip() if next_steps else "",
            "branch": branch.strip() if branch else None,
            "commit": commit.strip() if commit else None,
            "evaluation_result": evaluation_result.strip() if evaluation_result else None,
            "recorded_at": recorded_at,
        }

        # Capture source for progress record
        captured = await runtime.sources.for_scope(scope_id).capture(
            CaptureSource(
                source_id=progress_id,
                content=json.dumps(progress_data, ensure_ascii=False),
                metadata={
                    "project_id": project_id,
                    "progress_id": progress_id,
                    "type": "progress",
                    "record_kind": record_kind,
                },
            )
        )

        # Flush to process sources into memory with native Source lineage
        await runtime.memory.for_scope(scope_id).flush()

        return {
            "progress_id": progress_id,
            "project_id": project_id,
            "record_kind": record_kind,
            "title": title.strip(),
            "status": status,
            "recorded_at": recorded_at,
            "source_sequence": captured.sequence,
            "source_ref": {
                "source_type": captured.source_ref.source_type,
                "source_id": captured.source_ref.source_id,
            },
        }

    async def list_progress(self, project_id: str) -> list[dict[str, Any]]:
        """List all progress records for a project with pagination.

        Args:
            project_id: Project ID

        Returns:
            List of progress records
        """
        if not project_id or not project_id.strip():
            raise ValueError("Project ID cannot be empty")

        runtime = self._require_runtime()

        # Find the scope for this project
        project = await self.get_project(project_id)
        if not project:
            return []

        scope_id = project["scope_id"]
        records = []

        # Paginate through all sources
        cursor = None
        while True:
            sources_page = await runtime.records.for_scope(scope_id).list_sources(
                limit=100, cursor=cursor
            )

            for source in sources_page.items:
                try:
                    data = json.loads(source.content)
                    if data.get("type") == "progress" and data.get("project_id") == project_id:
                        records.append({
                            "progress_id": data["progress_id"],
                            "record_kind": data.get("record_kind", "progress"),
                            "project_id": data["project_id"],
                            "title": data["title"],
                            "body": data["body"],
                            "owner": data.get("owner"),
                            "status": data.get("status"),
                            "next_steps": data.get("next_steps"),
                            "branch": data.get("branch"),
                            "commit": data.get("commit"),
                            "evaluation_result": data.get("evaluation_result"),
                            "recorded_at": data.get("recorded_at"),
                        })
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"Failed to parse progress source: {e}")
                    continue

            if sources_page.next_cursor:
                cursor = sources_page.next_cursor
            else:
                break

        # Sort by recorded_at descending
        records.sort(key=lambda x: x.get("recorded_at", ""), reverse=True)
        return records

    async def query_handoff(self, project_id: str, question: str) -> dict[str, Any]:
        """Query handoff context using PowerContext memory search and context preparation.

        Args:
            project_id: Project ID
            question: Query question (must be non-empty)

        Returns:
            Handoff context with sources and citations

        Raises:
            ValueError: If project_id or question is empty
        """
        if not project_id or not project_id.strip():
            raise ValueError("Project ID cannot be empty")
        if not question or not question.strip():
            raise ValueError("Question cannot be empty")

        runtime = self._require_runtime()

        # Find the scope for this project
        project = await self.get_project(project_id)
        if not project:
            raise ProjectNotFoundError(f"Project {project_id} not found")

        scope_id = project["scope_id"]
        context_items = []
        sources_with_citations = []

        # Search memory for relevant context
        search_result = await runtime.memory.for_scope(scope_id).search(
            SearchMemoryRequest(query=question.strip(), mode="fts", limit=10)
        )

        # Keep PowerContext's actual ranked hits and their native source lineage.
        for hit in search_result.hits:
            entry = await runtime.records.for_scope(scope_id).current_memory_entry(
                hit.memory_ref.artifact_id, hit.entry_id
            )
            if not entry.sources:
                raise RuntimeError("检索命中的记忆缺少原始来源，无法生成可核对引用")
            for source_ref in entry.sources:
                source_record = await runtime.records.for_scope(scope_id).get_source(
                    source_ref.source_type, source_ref.source_id
                )
                try:
                    source_data = json.loads(source_record.content)
                except (TypeError, json.JSONDecodeError) as error:
                    raise RuntimeError("原始进展记录无法解析") from error
                if source_data.get("type") != "progress":
                    raise RuntimeError("记忆引用没有指向原始进展记录")
                sources_with_citations.append({
                    "type": "progress",
                    "title": source_data["title"],
                    "record_kind": source_data.get("record_kind", "progress"),
                    "body": source_data["body"],
                    "status": source_data["status"],
                    "recorded_at": source_data["recorded_at"],
                    "progress_id": source_data["progress_id"],
                    "source_ref": source_ref.model_dump(mode="json"),
                    "memory_ref": hit.memory_ref.model_dump(mode="json"),
                    "entry_id": entry.entry_id,
                    "entry_version_id": entry.entry_version_id,
                })
            context_items.append({
                "content": hit.text,
                "entry_id": hit.entry_id,
                "memory_ref": hit.memory_ref.model_dump(mode="json"),
                "score": hit.score,
            })

        # Prepare context for comprehensive handoff
        context_result = await runtime.context.for_scope(scope_id).prepare(
            PrepareContextRequest(query=question.strip())
        )

        # Get recent progress records as separate section (not as query matches)
        recent_progress = await self.list_progress(project_id)
        recent_sources = []
        for record in recent_progress[:5]:  # Top 5 recent
            recent_sources.append({
                "type": "progress",
                "title": record["title"],
                "body": record["body"],
                "status": record["status"],
                "recorded_at": record["recorded_at"],
                "progress_id": record["progress_id"],
                "note": "最近进展（非查询匹配）",
            })

        # Generate summary based on actual results
        if not context_items:
            summary = f"没有找到与 '{question.strip()}' 相关的记录。"
            if recent_sources:
                summary += f" 显示最近 {len(recent_sources)} 条进展供参考。"
        else:
            summary_parts = [f"找到 {len(context_items)} 条相关记忆"]
            if recent_sources:
                summary_parts.append(f"另有 {len(recent_sources)} 条最近进展")
            summary = "，".join(summary_parts) + "。"

        return {
            "project_id": project_id,
            "question": question.strip(),
            "context_items": context_items,
            "sources": sources_with_citations,  # Genuine citations with native SourceRef
            "recent_progress": recent_sources,  # Separate section
            "summary": summary,
            "prepared_context": {
                "status": context_result.status,
                "content": context_result.content if context_result.status == "ready" else None,
                "note": "此上下文由 PowerContext prepare 生成，非模型推理结果",
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def get_version_status(self, project_id: str) -> dict[str, Any]:
        """Get code version vs evaluation version status.

        Args:
            project_id: Project ID

        Returns:
            Version status with detailed state
        """
        if not project_id or not project_id.strip():
            raise ValueError("Project ID cannot be empty")

        progress_records = await self.list_progress(project_id)

        # Separate records by kind
        code_records = [r for r in progress_records if r.get("record_kind") == "code" and r.get("commit")]
        eval_records = [r for r in progress_records if r.get("record_kind") == "evaluation" and r.get("evaluation_result")]
        progress_only = [r for r in progress_records if r.get("record_kind") == "progress"]

        latest_code = None
        latest_eval = None

        if code_records:
            # Get the most recent code record
            latest_code_record = code_records[0]  # Already sorted by recorded_at desc
            latest_code = {
                "commit": latest_code_record["commit"],
                "branch": latest_code_record.get("branch"),
                "recorded_at": latest_code_record["recorded_at"],
                "progress_id": latest_code_record["progress_id"],
            }

        if eval_records:
            # Get the most recent eval record
            latest_eval_record = eval_records[0]
            latest_eval = {
                "evaluation_result": latest_eval_record["evaluation_result"],
                "commit": latest_eval_record.get("commit"),
                "branch": latest_eval_record.get("branch"),
                "recorded_at": latest_eval_record["recorded_at"],
                "progress_id": latest_eval_record["progress_id"],
            }

        # Determine status
        has_no_code = latest_code is None
        has_no_eval = latest_eval is None
        has_unevaluated_updates = not has_no_code and has_no_eval
        branch_differs = False
        commit_differs = False

        if not has_no_code and not has_no_eval:
            # Both exist - check if they differ
            if latest_code["commit"] != latest_eval.get("commit"):
                commit_differs = True
                has_unevaluated_updates = True
            if latest_code.get("branch") and latest_eval.get("branch"):
                if latest_code["branch"] != latest_eval["branch"]:
                    branch_differs = True
                    has_unevaluated_updates = True

        return {
            "project_id": project_id,
            "latest_code": latest_code,
            "latest_evaluation": latest_eval,
            "has_no_code_records": has_no_code,
            "has_no_evaluation_records": has_no_eval,
            "has_unevaluated_updates": has_unevaluated_updates,
            "branch_differs": branch_differs,
            "commit_differs": commit_differs,
            "total_progress_records": len(progress_only),
            "total_code_records": len(code_records),
            "total_evaluation_records": len(eval_records),
            "status_description": self._describe_version_status(
                has_no_code, has_no_eval, has_unevaluated_updates, branch_differs, commit_differs
            ),
        }

    def _describe_version_status(
        self,
        has_no_code: bool,
        has_no_eval: bool,
        has_unevaluated_updates: bool,
        branch_differs: bool,
        commit_differs: bool,
    ) -> str:
        """Generate human-readable version status description."""
        if has_no_code:
            return "暂无代码版本记录"
        if has_no_eval:
            return "有代码版本但从未评测"
        if has_unevaluated_updates:
            parts = ["有未评测更新"]
            if branch_differs:
                parts.append("分支不同")
            if commit_differs:
                parts.append("commit 不同")
            return "，".join(parts)
        return "最新代码版本已评测"

    async def load_demo_data(self, project_id: str | None = None) -> dict[str, Any]:
        """Load demo data (idempotent with stable demo project identity).

        Args:
            project_id: Optional project ID to load demo data into.
                       If None, uses stable demo project.

        Returns:
            Demo data loading result
        """
        runtime = self._require_runtime()

        # Use stable demo project if no project_id provided
        if not project_id:
            # Try to find existing demo project by idempotency key
            demo_project = None
            projects = await self.list_projects()
            for proj in projects:
                if proj["name"] == DEMO_PROJECT_NAME:
                    demo_project = proj
                    break

            if not demo_project:
                # Create demo project with stable idempotency key
                try:
                    scope = await runtime.scopes.create(
                        ScopeDraft(
                            title=DEMO_PROJECT_NAME,
                            summary=DEMO_PROJECT_DESCRIPTION,
                            idempotency_key=DEMO_PROJECT_IDEMPOTENCY_KEY,
                        )
                    )

                    demo_project_id = f"proj-demo-{uuid4().hex[:8]}"
                    project_data = {
                        "type": "project",
                        "project_id": demo_project_id,
                        "scope_id": scope.scope_id,
                        "name": DEMO_PROJECT_NAME,
                        "description": DEMO_PROJECT_DESCRIPTION,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "is_demo": True,
                    }

                    await runtime.sources.for_scope(scope.scope_id).capture(
                        CaptureSource(
                            source_id=f"project-meta-{demo_project_id}",
                            content=json.dumps(project_data, ensure_ascii=False),
                            metadata={"project_id": demo_project_id, "type": "project"},
                        )
                    )

                    demo_project = {
                        "project_id": demo_project_id,
                        "scope_id": scope.scope_id,
                        "name": DEMO_PROJECT_NAME,
                        "description": DEMO_PROJECT_DESCRIPTION,
                    }
                except ScopeIdempotencyConflictError:
                    # Demo project already exists, find it
                    projects = await self.list_projects()
                    for proj in projects:
                        if proj["name"] == DEMO_PROJECT_NAME:
                            demo_project = proj
                            break

            project_id = demo_project["project_id"]

        # Check if demo data already exists in this project
        existing = await self.list_progress(project_id)
        if existing:
            return {
                "status": "already_loaded",
                "project_id": project_id,
                "message": "演示数据已存在，跳过重复导入",
            }

        # Load demo progress records with different record_kinds
        demo_records = [
            {
                "title": "完成用户认证模块",
                "body": "实现了基于 JWT 的用户认证，包括登录、注册和令牌刷新功能。所有测试通过。（虚构样例）",
                "owner": "张三",
                "status": "已完成",
                "next_steps": "需要进行安全审计和性能测试",
                "branch": "feature/auth",
                "commit": "a1b2c3d4e5f6789012345678901234567890abcd",
                "evaluation_result": None,
                "record_kind": "code",
            },
            {
                "title": "用户认证模块评测",
                "body": "通过单元测试，覆盖率 95%。（虚构样例，非本作品实测效果）",
                "owner": "张三",
                "status": "已完成",
                "next_steps": "",
                "branch": "feature/auth",
                "commit": "a1b2c3d4e5f6789012345678901234567890abcd",
                "evaluation_result": "通过单元测试，覆盖率 95%",
                "record_kind": "evaluation",
            },
            {
                "title": "优化数据库查询性能",
                "body": "对核心查询进行了索引优化，响应时间从 500ms 降至 50ms。生产环境验证通过。（虚构样例）",
                "owner": "李四",
                "status": "已完成",
                "next_steps": "监控生产环境性能指标",
                "branch": "optimize/db-queries",
                "commit": "f6e5d4c3b2a10987654321098765432109876543",
                "evaluation_result": None,
                "record_kind": "code",
            },
            {
                "title": "修复支付流程 bug",
                "body": "修复了在高并发场景下支付状态同步的问题。已提交 QA 验证。（虚构样例）",
                "owner": "王五",
                "status": "进行中",
                "next_steps": "等待 QA 验证和灰度发布",
                "branch": "fix/payment-sync",
                "commit": "1a2b3c4d5e6f789012345678901234567890abcd",
                "evaluation_result": None,
                "record_kind": "progress",
            },
        ]

        created = []
        for record in demo_records:
            result = await self.create_progress(
                project_id=project_id,
                **record,
            )
            created.append(result)

        return {
            "status": "loaded",
            "project_id": project_id,
            "records_created": len(created),
            "message": "演示数据已成功加载（所有数据均为虚构样例，不代表真实评测结果）",
        }
