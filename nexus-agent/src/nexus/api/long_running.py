"""Long-running workflow API — pause, resume, cancel autonomous workflows.

Endpoints:
- ``GET /long-running`` — list all long-running workflows
- ``GET /long-running/{id}`` — get workflow status
- ``POST /long-running/{id}/pause`` — pause a running workflow
- ``POST /long-running/{id}/resume`` — resume a paused workflow
- ``POST /long-running/{id}/cancel`` — cancel a workflow
- ``POST /long-running/{id}/notify`` — set notification target

No hardcoded workflow types. All driven by DB metadata.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from sqlalchemy import select, update

from nexus.db.base import get_session_factory

logger = structlog.get_logger("nexus.api.long_running")

router = APIRouter(prefix="/long-running", tags=["long_running"])


async def _get_workflow(workflow_id: str) -> dict[str, Any]:
    """Fetch a LongRunningWorkflow by ID."""
    from nexus.db.models.long_running_workflow import LongRunningWorkflow

    try:
        wf_id = uuid.UUID(workflow_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid workflow ID")

    async with get_session_factory()() as session:
        result = await session.execute(
            select(LongRunningWorkflow).where(LongRunningWorkflow.id == wf_id)
        )
        wf = result.scalar_one_or_none()
        if wf is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        return {
            "id": str(wf.id),
            "session_id": str(wf.session_id),
            "name": wf.name,
            "status": wf.status,
            "schedule_cron": wf.schedule_cron,
            "last_run_at": str(wf.last_run_at) if wf.last_run_at else None,
            "next_run_at": str(wf.next_run_at) if wf.next_run_at else None,
            "run_count": wf.run_count,
            "max_runs": wf.max_runs,
            "total_cost_usd": wf.total_cost_usd,
            "error_message": wf.error_message,
            "created_at": str(wf.created_at),
            "updated_at": str(wf.updated_at),
        }


@router.get("")
async def list_workflows() -> list[dict[str, Any]]:
    """List all long-running workflows."""
    from nexus.db.models.long_running_workflow import LongRunningWorkflow

    async with get_session_factory()() as session:
        result = await session.execute(
            select(LongRunningWorkflow).order_by(LongRunningWorkflow.created_at.desc())
        )
        workflows = result.scalars().all()
        return [
            {
                "id": str(wf.id),
                "session_id": str(wf.session_id),
                "name": wf.name,
                "status": wf.status,
                "schedule_cron": wf.schedule_cron,
                "run_count": wf.run_count,
                "next_run_at": str(wf.next_run_at) if wf.next_run_at else None,
                "created_at": str(wf.created_at),
            }
            for wf in workflows
        ]


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str) -> dict[str, Any]:
    """Get the status of a specific workflow."""
    return await _get_workflow(workflow_id)


@router.post("/{workflow_id}/pause")
async def pause_workflow(workflow_id: str) -> dict[str, str]:
    """Pause a running workflow."""
    from nexus.db.models.long_running_workflow import LongRunningWorkflow

    async with get_session_factory()() as session:
        result = await session.execute(
            update(LongRunningWorkflow)
            .where(
                LongRunningWorkflow.id == uuid.UUID(workflow_id),
                LongRunningWorkflow.status == "running",
            )
            .values(status="paused")
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Running workflow not found")

    logger.info("long_running.paused", workflow_id=workflow_id)
    return {"status": "paused", "workflow_id": workflow_id}


@router.post("/{workflow_id}/resume")
async def resume_workflow(workflow_id: str) -> dict[str, str]:
    """Resume a paused workflow."""
    from nexus.db.models.long_running_workflow import LongRunningWorkflow

    async with get_session_factory()() as session:
        result = await session.execute(
            update(LongRunningWorkflow)
            .where(
                LongRunningWorkflow.id == uuid.UUID(workflow_id),
                LongRunningWorkflow.status == "paused",
            )
            .values(status="running")
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Paused workflow not found")

    logger.info("long_running.resumed", workflow_id=workflow_id)
    return {"status": "resumed", "workflow_id": workflow_id}


@router.post("/{workflow_id}/cancel")
async def cancel_workflow(workflow_id: str) -> dict[str, str]:
    """Cancel a workflow (completed terminal status)."""
    from nexus.db.models.long_running_workflow import LongRunningWorkflow

    async with get_session_factory()() as session:
        result = await session.execute(
            update(LongRunningWorkflow)
            .where(LongRunningWorkflow.id == uuid.UUID(workflow_id))
            .values(status="completed")
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Workflow not found")

    logger.info("long_running.cancelled", workflow_id=workflow_id)
    return {"status": "completed", "workflow_id": workflow_id}
