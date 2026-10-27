"""FastAPI application for RelayDesk."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, SecretStr

from .powercontext_service import PowerContextService, ProjectNotFoundError


def _request_error(error: ValueError) -> HTTPException:
    return HTTPException(
        status_code=404 if isinstance(error, ProjectNotFoundError) else 422,
        detail=str(error),
    )


# Global service instance
_service: PowerContextService | None = None


def get_service() -> PowerContextService:
    """Get the global PowerContext service instance."""
    if _service is None:
        raise RuntimeError("Service not initialized")
    return _service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup the PowerContext service."""
    global _service

    # Initialize service
    data_dir = Path(os.environ.get("RELAYDESK_DATA_DIR", "./data"))

    _service = PowerContextService(data_dir=data_dir)
    await _service.initialize()

    yield

    # Cleanup
    if _service:
        await _service.shutdown()
        _service = None


app = FastAPI(
    title="RelayDesk 接力台",
    description="Team handoff context management powered by PowerContext",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for local development (restricted to localhost)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=False,  # No credentials in development
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


# Request/Response models
class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProgressCreate(BaseModel):
    project_id: str
    title: str
    body: str
    owner: str | None = None
    status: str = "进行中"
    next_steps: str = ""
    branch: str | None = None
    commit: str | None = None
    evaluation_result: str | None = None
    record_kind: str = "progress"


class HandoffQuery(BaseModel):
    project_id: str
    question: str


class DemoDataLoad(BaseModel):
    project_id: str | None = None


# API endpoints
@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "RelayDesk"}


@app.get("/api/projects")
async def list_projects():
    """List all projects."""
    service = get_service()
    projects = await service.list_projects()
    return {"projects": projects}


@app.post("/api/projects")
async def create_project(project: ProjectCreate):
    """Create a new project."""
    service = get_service()
    try:
        result = await service.create_project(project.name, project.description)
        return result
    except ValueError as e:
        raise _request_error(e)


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    """Get project details with progress overview."""
    service = get_service()
    try:
        result = await service.get_project(project_id)
    except ValueError as e:
        raise _request_error(e)
    if not result:
        raise HTTPException(status_code=404, detail="Project not found")
    return result


@app.get("/api/projects/{project_id}/progress")
async def list_progress(project_id: str):
    """List all progress records for a project."""
    service = get_service()
    try:
        records = await service.list_progress(project_id)
    except ValueError as e:
        raise _request_error(e)
    return {"records": records}


@app.post("/api/progress")
async def create_progress(progress: ProgressCreate):
    """Create a new progress record."""
    service = get_service()
    try:
        result = await service.create_progress(
            project_id=progress.project_id,
            title=progress.title,
            body=progress.body,
            owner=progress.owner,
            status=progress.status,
            next_steps=progress.next_steps,
            branch=progress.branch,
            commit=progress.commit,
            evaluation_result=progress.evaluation_result,
            record_kind=progress.record_kind,
        )
        return result
    except ValueError as e:
        raise _request_error(e)


@app.post("/api/handoff/query")
async def query_handoff(query: HandoffQuery):
    """Query handoff context using PowerContext."""
    service = get_service()
    try:
        result = await service.query_handoff(query.project_id, query.question)
        return result
    except ValueError as e:
        raise _request_error(e)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/api/demo/load")
async def load_demo_data(request: DemoDataLoad):
    """Load demo data (idempotent)."""
    service = get_service()
    result = await service.load_demo_data(request.project_id)
    return result


@app.get("/api/projects/{project_id}/versions")
async def get_version_status(project_id: str):
    """Get code version vs evaluation version status."""
    service = get_service()
    try:
        result = await service.get_version_status(project_id)
        return result
    except ValueError as e:
        raise _request_error(e)


# Serve static frontend files
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    async def serve_index():
        """Serve the main HTML page."""
        return FileResponse(static_dir / "index.html")

    @app.get("/favicon.ico")
    async def serve_favicon():
        """Serve favicon if exists."""
        favicon_path = static_dir / "favicon.ico"
        if favicon_path.exists():
            return FileResponse(favicon_path)
        return {"status": "no favicon"}
