"""Projects & Artifacts API — cross-session project management + artifact evolution.

Endpoints:
- ``GET/POST /projects`` — list/create projects
- ``GET/PUT/DELETE /projects/{id}`` — get/update/archive a project
- ``GET/POST /projects/{id}/artifacts`` — list/create artifacts
- ``GET /projects/{id}/artifacts/{aid}`` — get artifact version
- ``POST /projects/{id}/artifacts/{aid}/fork`` — fork an artifact (new branch)

No hardcoded project types or artifact kinds. All driven by DB metadata.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.base import get_session
from nexus.db.models.artifact import Artifact
from nexus.db.models.project import Project

logger = structlog.get_logger("nexus.api.projects")

router = APIRouter(prefix="/projects", tags=["projects"])


# ── Project CRUD ──────────────────────────────────────────────────────────────


@router.get("", response_model=list[dict[str, Any]])
async def list_projects(
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """List all projects, ordered by most recently updated."""
    result = await session.execute(
        select(Project).order_by(Project.updated_at.desc())
    )
    return [_project_to_dict(p) for p in result.scalars().all()]


@router.post("", status_code=201)
async def create_project(
    body: dict[str, Any],
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new project."""
    project = Project(
        name=body.get("name", "Untitled Project"),
        description=body.get("description", ""),
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    logger.info("project.created", project_id=str(project.id), name=project.name)
    return _project_to_dict(project)


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a single project by ID."""
    project = await _load_project(project_id, session)
    return _project_to_dict(project)


@router.put("/{project_id}")
async def update_project(
    project_id: str,
    body: dict[str, Any],
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update project metadata."""
    project = await _load_project(project_id, session)
    if "name" in body:
        project.name = body["name"]
    if "description" in body:
        project.description = body["description"]
    if "status" in body:
        project.status = body["status"]
    await session.commit()
    await session.refresh(project)
    return _project_to_dict(project)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Archive (soft-delete) a project."""
    project = await _load_project(project_id, session)
    project.status = "archived"
    await session.commit()


# ── Artifact CRUD ─────────────────────────────────────────────────────────────


@router.get("/{project_id}/artifacts", response_model=list[dict[str, Any]])
async def list_artifacts(
    project_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """List all artifacts for a project."""
    await _load_project(project_id, session)
    result = await session.execute(
        select(Artifact)
        .where(Artifact.project_id == uuid.UUID(project_id))
        .order_by(Artifact.created_at.desc())
    )
    return [_artifact_to_dict(a) for a in result.scalars().all()]


@router.post("/{project_id}/artifacts", status_code=201)
async def create_artifact(
    project_id: str,
    body: dict[str, Any],
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new artifact version under a project."""
    await _load_project(project_id, session)

    content = body.get("content", {})
    content_hash = _compute_hash(content)
    parent_id = body.get("parent_artifact_id")

    # Determine next version number
    if parent_id:
        parent = await session.get(Artifact, uuid.UUID(parent_id))
        next_version = (parent.version + 1) if parent else 1
    else:
        next_version = 1

    artifact = Artifact(
        project_id=uuid.UUID(project_id),
        kind=body.get("kind", "dashboard"),
        name=body.get("name", ""),
        parent_artifact_id=uuid.UUID(parent_id) if parent_id else None,
        content=content,
        content_hash=content_hash,
        version=next_version,
    )
    session.add(artifact)
    await session.commit()
    await session.refresh(artifact)
    logger.info(
        "artifact.created",
        project_id=project_id,
        kind=artifact.kind,
        version=artifact.version,
    )
    return _artifact_to_dict(artifact)


@router.get("/{project_id}/artifacts/{artifact_id}")
async def get_artifact(
    project_id: str,
    artifact_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a specific artifact version."""
    artifact = await _load_artifact(project_id, artifact_id, session)
    return _artifact_to_dict(artifact)


@router.post("/{project_id}/artifacts/{artifact_id}/fork")
async def fork_artifact(
    project_id: str,
    artifact_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Fork an artifact — create a new version as a child of the specified one."""
    parent = await _load_artifact(project_id, artifact_id, session)
    child = Artifact(
        project_id=uuid.UUID(project_id),
        kind=parent.kind,
        name=f"{parent.name} (fork)",
        parent_artifact_id=uuid.UUID(artifact_id),
        content=dict(parent.content),
        content_hash=parent.content_hash,
        version=parent.version + 1,
    )
    session.add(child)
    await session.commit()
    await session.refresh(child)
    logger.info("artifact.forked", project_id=project_id, parent=artifact_id)
    return _artifact_to_dict(child)


# ── Session linking ───────────────────────────────────────────────────────────


@router.post("/{project_id}/sessions", status_code=201)
async def create_project_session(
    project_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Create a new session under a project (returns session ID for redirect)."""
    from nexus.db.models.session import Session as SessionModel

    project = await _load_project(project_id, session)
    new_session = SessionModel(
        project_id=uuid.UUID(project_id),
        title=f"Session in {project.name}",
    )
    session.add(new_session)
    await session.commit()
    await session.refresh(new_session)
    return {"session_id": str(new_session.id), "project_id": project_id}


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _load_project(project_id: str, db: AsyncSession) -> Project:
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID")
    project = await db.get(Project, pid)
    if project is None or project.status == "archived":
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _load_artifact(project_id: str, artifact_id: str, db: AsyncSession) -> Artifact:
    try:
        aid = uuid.UUID(artifact_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid artifact ID")
    artifact = await db.get(Artifact, aid)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if str(artifact.project_id) != project_id:
        raise HTTPException(status_code=404, detail="Artifact not in this project")
    return artifact


def _project_to_dict(p: Project) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "name": p.name,
        "description": p.description,
        "status": p.status,
        "created_at": str(p.created_at),
        "updated_at": str(p.updated_at),
    }


def _artifact_to_dict(a: Artifact) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "project_id": str(a.project_id),
        "kind": a.kind,
        "name": a.name,
        "parent_artifact_id": str(a.parent_artifact_id) if a.parent_artifact_id else None,
        "version": a.version,
        "content_hash": a.content_hash,
        "created_at": str(a.created_at),
    }


def _compute_hash(content: dict[str, Any]) -> str:
    import hashlib, json
    raw = json.dumps(content, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
