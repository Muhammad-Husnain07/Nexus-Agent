"""Workflows API — register, version, activate and inspect deterministic workflows.

Developers define reusable workflows for deterministic business processes
(onboarding, invoice approval, etc.) at runtime. The template engine matches
these definitions by ``trigger_intent_pattern`` and executes them step-wise;
hybrid steps (``dynamic: true``) and workflow references (``workflow_ref``)
keep deterministic flows composable with dynamic planning.

No workflow name, step, or capability is hardcoded — everything is
metadata-driven and validated against the schema declared in the definition.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from nexus.db.base import async_session as _session_factory
from nexus.db.models.workflow_definition import WorkflowDefinition, WorkflowInstance

logger = structlog.get_logger("nexus.api.workflows")

router = APIRouter(prefix="/workflows", tags=["workflows"])

# Step keys allowed per the WorkflowDefinition model docstring. Any other
# keys are rejected so developers get immediate feedback on typos.
_ALLOWED_STEP_KEYS = frozenset({
    "id", "description", "intent", "capability", "requires_input", "question",
    "inputs", "dynamic", "workflow_ref", "template",
})


class WorkflowStep(BaseModel):
    """A single step in a workflow definition."""

    id: str = Field(description="Stable step id (e.g. step_1), referenced by ${step_1} inputs")
    description: str = Field(default="", description="What this step does")
    intent: str | None = Field(default=None, description="Capability intent name (deterministic step)")
    capability: str | None = Field(default=None, description="Legacy capability alias for intent")
    requires_input: bool = Field(default=False, description="Ask the user for this step's input")
    question: str | None = Field(default=None, description="Question asked when requires_input")
    inputs: dict[str, Any] = Field(default_factory=dict, description="Step inputs; ${step_X} references")
    dynamic: bool = Field(default=False, description="Hybrid step: plan this step with dynamic planning")
    workflow_ref: str | None = Field(default=None, description="Reuse another workflow as a building block")
    template: str | None = Field(default=None, description="Expand a workflow template inline")

    @field_validator("id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError("step id must be 1-100 chars")
        return v


class WorkflowDefinitionCreate(BaseModel):
    """Payload to register a new deterministic workflow."""

    name: str = Field(min_length=1, max_length=255, description="Unique workflow name")
    description: str = Field(default="", description="Human-readable description")
    trigger_intent_pattern: str = Field(
        default="", description="Intent pattern matched against user requests"
    )
    steps: list[WorkflowStep] = Field(
        min_length=1, description="Ordered steps — at least one required"
    )
    priority: int = Field(default=0, ge=0, description="Match priority (higher = matched first)")
    max_nodes: int = Field(default=10, ge=1, description="Max steps before dynamic hand-off")
    enabled: bool = Field(default=True, description="Whether the workflow is active")

    @field_validator("steps")
    @classmethod
    def _validate_steps(cls, steps: list[WorkflowStep]) -> list[WorkflowStep]:
        ids = [s.id for s in steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step ids must be unique within a workflow")
        for step in steps:
            if not (step.intent or step.capability or step.dynamic or step.workflow_ref or step.template or step.requires_input):
                raise ValueError(
                    f"step {step.id!r} must declare intent, capability, dynamic, "
                    "workflow_ref, template, or requires_input"
                )
        return steps


class WorkflowDefinitionUpdate(BaseModel):
    """Fields that may be updated on an existing workflow."""

    description: str | None = Field(default=None, description="Updated description")
    trigger_intent_pattern: str | None = Field(default=None, description="Updated intent pattern")
    steps: list[WorkflowStep] | None = Field(default=None, description="Updated steps (bumps version)")
    priority: int | None = Field(default=None, ge=0, description="Updated priority")
    max_nodes: int | None = Field(default=None, ge=1, description="Updated max nodes")
    enabled: bool | None = Field(default=None, description="Enable/disable toggle")

    @field_validator("steps")
    @classmethod
    def _validate_steps(cls, steps: list[WorkflowStep] | None) -> list[WorkflowStep] | None:
        if steps is None:
            return None
        ids = [s.id for s in steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step ids must be unique within a workflow")
        for step in steps:
            if not (step.intent or step.capability or step.dynamic or step.workflow_ref or step.template or step.requires_input):
                raise ValueError(
                    f"step {step.id!r} must declare intent, capability, dynamic, "
                    "workflow_ref, template, or requires_input"
                )
        return steps


def _workflow_to_dict(wf: WorkflowDefinition) -> dict[str, Any]:
    """Serialize a workflow definition row (no hardcoded field values)."""
    return {
        "id": str(wf.id),
        "name": wf.name,
        "description": wf.description,
        "trigger_intent_pattern": wf.trigger_intent_pattern,
        "steps": wf.steps,
        "priority": wf.priority,
        "max_nodes": wf.max_nodes,
        "enabled": wf.enabled,
        "version": wf.version,
        "created_at": wf.created_at.isoformat() if wf.created_at else None,
        "updated_at": wf.updated_at.isoformat() if wf.updated_at else None,
    }


def _instance_to_dict(inst: WorkflowInstance) -> dict[str, Any]:
    """Serialize a workflow instance row."""
    return {
        "id": str(inst.id),
        "definition_id": str(inst.definition_id),
        "session_id": str(inst.session_id) if inst.session_id else None,
        "status": inst.status,
        "current_step": inst.current_step,
        "collected": inst.collected,
        "error_message": inst.error_message,
        "started_at": inst.started_at.isoformat() if inst.started_at else None,
        "completed_at": inst.completed_at.isoformat() if inst.completed_at else None,
    }


async def _get_workflow(session: Any, workflow_id: str) -> WorkflowDefinition:
    try:
        wf_id = uuid.UUID(workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid workflow id") from exc
    wf = await session.get(WorkflowDefinition, wf_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf


async def _refresh_workflow_embedding(session: Any, wf: WorkflowDefinition) -> None:
    """(Re)generate the workflow's hybrid-matching embedding (best-effort)."""
    try:
        import hashlib

        from nexus.config.settings import get_settings as _wf_settings
        from nexus.llm.client import LLMClient

        text = f"{wf.name} {wf.trigger_intent_pattern} {wf.description}"
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        try:
            from nexus.redis_client.client import get_redis_client

            _redis = get_redis_client()
            import json as _json

            cached = await _redis.get(f"tpl_embed:{text_hash}") if _redis else None
            if cached:
                wf.embedding = _json.loads(cached)
                await session.commit()
                await session.refresh(wf)
                return
        except Exception:
            pass
        model = _wf_settings().llm.embedding_model
        embeddings = await LLMClient().embed(model, [text])
        if embeddings and embeddings[0]:
            wf.embedding = embeddings[0]
            await session.commit()
            # expire_on_commit expires attributes — reload before returning so
            # callers can serialize the row without a lazy-load in async ctx.
            await session.refresh(wf)
    except Exception as exc:
        logger.warning("workflows.embedding_failed", workflow=wf.name, error=str(exc)[:200])


@router.post("", status_code=201)
async def create_workflow(body: WorkflowDefinitionCreate) -> dict[str, Any]:
    """Register a new deterministic workflow definition (version 1)."""
    async with _session_factory() as session:
        existing = await session.execute(
            select(WorkflowDefinition).where(WorkflowDefinition.name == body.name)
        )
        if existing.scalars().first() is not None:
            raise HTTPException(status_code=409, detail="Workflow name already exists")

        wf = WorkflowDefinition(
            name=body.name,
            description=body.description,
            trigger_intent_pattern=body.trigger_intent_pattern,
            steps=[s.model_dump() for s in body.steps],
            priority=body.priority,
            max_nodes=body.max_nodes,
            enabled=body.enabled,
            version=1,
        )
        session.add(wf)
        await session.commit()
        await session.refresh(wf)
        logger.info("workflows.created", workflow=wf.name, steps=len(wf.steps))
        # Hybrid matching embedding (Phase 6): best-effort, fuzzy-only fallback
        # when embedding generation is unavailable.
        await _refresh_workflow_embedding(session, wf)
        data = _workflow_to_dict(wf)
        # Durable audit trail for workflow registration.
        from nexus.events.service import enqueue_outbox, write_audit_log

        try:
            await write_audit_log(
                action="workflow_registered",
                resource_type="workflow",
                resource_id=data["id"],
                after=data,
            )
            await enqueue_outbox(
                event_type="workflow.registered",
                aggregate_type="workflow",
                aggregate_id=data["id"],
                payload={"name": data["name"], "version": data["version"]},
            )
        except Exception as exc:
            logger.warning("workflows.audit_failed", error=str(exc)[:200])
        return data


@router.get("")
async def list_workflows(
    enabled: bool | None = Query(default=None, description="Filter by enabled state"),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """List workflow definitions (optionally only enabled ones)."""
    async with _session_factory() as session:
        stmt = select(WorkflowDefinition).order_by(
            WorkflowDefinition.priority.desc(), WorkflowDefinition.name
        )
        if enabled is not None:
            stmt = stmt.where(WorkflowDefinition.enabled == enabled)  # noqa: E712
        result = await session.execute(stmt.limit(limit))
        workflows = result.scalars().all()
        return {
            "workflows": [_workflow_to_dict(w) for w in workflows],
            "count": len(workflows),
        }


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str) -> dict[str, Any]:
    """Get a single workflow definition by id."""
    async with _session_factory() as session:
        wf = await _get_workflow(session, workflow_id)
        return _workflow_to_dict(wf)


@router.put("/{workflow_id}")
async def update_workflow(
    workflow_id: str,
    body: WorkflowDefinitionUpdate,
) -> dict[str, Any]:
    """Update a workflow. Changing steps/pattern bumps the version."""
    async with _session_factory() as session:
        wf = await _get_workflow(session, workflow_id)
        changed = False
        if body.description is not None:
            wf.description = body.description
        if body.trigger_intent_pattern is not None:
            wf.trigger_intent_pattern = body.trigger_intent_pattern
            changed = True
        if body.steps is not None:
            wf.steps = [s.model_dump() for s in body.steps]
            changed = True
        if body.priority is not None:
            wf.priority = body.priority
        if body.max_nodes is not None:
            wf.max_nodes = body.max_nodes
        if body.enabled is not None:
            wf.enabled = body.enabled
        if changed:
            wf.version += 1
        await session.commit()
        await session.refresh(wf)
        logger.info("workflows.updated", workflow=wf.name, version=wf.version)
        if changed:
            await _refresh_workflow_embedding(session, wf)
        data = _workflow_to_dict(wf)
        from nexus.events.service import write_audit_log

        try:
            await write_audit_log(
                action="workflow_updated",
                resource_type="workflow",
                resource_id=data["id"],
                after=data,
            )
        except Exception as exc:
            logger.warning("workflows.audit_failed", error=str(exc)[:200])
        return data


@router.post("/{workflow_id}/activate")
async def activate_workflow(workflow_id: str) -> dict[str, Any]:
    """Enable a workflow so the template engine can match it."""
    async with _session_factory() as session:
        wf = await _get_workflow(session, workflow_id)
        wf.enabled = True
        await session.commit()
        await session.refresh(wf)
        data = _workflow_to_dict(wf)
        from nexus.events.service import write_audit_log

        try:
            await write_audit_log(
                action="workflow_activated",
                resource_type="workflow",
                resource_id=data["id"],
                after=data,
            )
        except Exception as exc:
            logger.warning("workflows.audit_failed", error=str(exc)[:200])
        return data


@router.post("/{workflow_id}/deactivate")
async def deactivate_workflow(workflow_id: str) -> dict[str, Any]:
    """Disable a workflow — it will no longer match user requests."""
    async with _session_factory() as session:
        wf = await _get_workflow(session, workflow_id)
        wf.enabled = False
        await session.commit()
        await session.refresh(wf)
        data = _workflow_to_dict(wf)
        from nexus.events.service import write_audit_log

        try:
            await write_audit_log(
                action="workflow_deactivated",
                resource_type="workflow",
                resource_id=data["id"],
                after=data,
            )
        except Exception as exc:
            logger.warning("workflows.audit_failed", error=str(exc)[:200])
        return data


@router.delete("/{workflow_id}", status_code=204)
async def delete_workflow(workflow_id: str) -> None:
    """Permanently delete a workflow definition (instances are preserved)."""
    async with _session_factory() as session:
        wf = await _get_workflow(session, workflow_id)
        await session.delete(wf)
        await session.commit()
        logger.info("workflows.deleted", workflow=wf.name)


@router.get("/{workflow_id}/instances")
async def list_workflow_instances(
    workflow_id: str,
    request: Request,
    status: str | None = Query(default=None, description="Filter by status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """List execution instances of a workflow definition.

    C3/P0-C: instances are scoped to the caller's sessions.
    """
    from nexus.security.ownership import accessible_session_ids  # noqa: PLC0415

    owned_ids = await accessible_session_ids(request)
    async with _session_factory() as session:
        await _get_workflow(session, workflow_id)
        stmt = (
            select(WorkflowInstance)
            .where(WorkflowInstance.definition_id == uuid.UUID(workflow_id))
            .order_by(WorkflowInstance.created_at.desc())
        )
        if owned_ids:
            stmt = stmt.where(WorkflowInstance.session_id.in_(owned_ids))
        else:
            stmt = stmt.where(WorkflowInstance.session_id.is_(None))
        if status:
            stmt = stmt.where(WorkflowInstance.status == status)  # noqa: E712
        result = await session.execute(stmt.limit(limit))
        instances = result.scalars().all()
        return {
            "instances": [_instance_to_dict(i) for i in instances],
            "count": len(instances),
        }
