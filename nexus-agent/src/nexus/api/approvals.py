"""FastAPI router for /api/v1/approvals — structured HITL approval management.

Provides endpoints for listing pending approvals, deciding on them, and
checking approval status — all backed by the ``Approval`` table and the
shared in-memory graph cache.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from langgraph.types import Command

from nexus.agent.graph import build_agent_graph
from nexus.agent.schemas import ApprovalAction
from nexus.config.settings import get_settings
from nexus.db.base import async_session
from nexus.db.context import get_tenant
from nexus.db.models.agent_run import Approval
from nexus.db.repositories.base import GenericRepository, TenantScopedRepository
from nexus.llm.client import LLMClient
from nexus.redis_client.client import get_redis_client
from nexus.redis_client.pubsub import EventBus
from nexus.security.rbac import Permission, require_permission
from nexus.tools.discovery import DynamicToolSelector
from nexus.tools.executor import ToolExecutor
from nexus.tools.registry import ToolRegistry

logger = structlog.get_logger("nexus.api.approvals")

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _build_graph_from_request(request: Request) -> Any:
    """Build a fresh compiled graph (stateless — state is in the Postgres checkpointer)."""
    settings = get_settings()
    tool_registry: ToolRegistry = request.app.state.tool_registry

    llm = LLMClient()
    event_bus: EventBus | None = None
    redis_client = get_redis_client()
    if redis_client is not None:
        event_bus = EventBus(redis_client)

    tool_executor = ToolExecutor(event_bus=event_bus)
    tool_selector = DynamicToolSelector(
        registry=tool_registry,
        llm_client=llm,
    )
    checkpointer = getattr(request.app.state, "checkpointer", None)

    return build_agent_graph(
        llm_client=llm,
        tool_selector=tool_selector,
        tool_executor=tool_executor,
        event_bus=event_bus,
        model=settings.llm.default_model,
        session_factory=async_session,
        checkpointer=checkpointer,
    )


@router.get("/pending/{session_id}")
async def list_pending_approvals(
    session_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Return all pending (not-yet-decided) approvals for *session_id*.

    Expired approvals (older than ``approval_timeout_hours``) are
    auto-rejected before being returned.
    """
    settings = get_settings().agent
    timeout_hours = settings.approval_timeout_hours
    cutoff = datetime.now(UTC) - timedelta(hours=timeout_hours)

    async with async_session() as session:
        repo = TenantScopedRepository(session, Approval)
        all_pending: list[Approval] = await repo.find(status="pending")

    # Filter by session_id (the Approval model doesn't have a direct FK to
    # session, so we check via the agent_run relationship or tool_call payload)
    session_pending: list[dict[str, Any]] = []
    auto_rejected: list[str] = []
    for approval in all_pending:
        tool_call = approval.tool_call or {}
        if tool_call.get("session_id") != str(session_id):
            continue

        # Auto-reject expired approvals
        if approval.created_at and approval.created_at < cutoff:
            auto_rejected.append(str(approval.id))
            async with async_session() as update_session:
                update_repo = GenericRepository(update_session, Approval)
                await update_repo.update(
                    approval.id,
                    status="rejected",
                    decided_at=datetime.now(UTC),
                    decision_payload={"action": "reject", "reason": "timeout"},
                )
                await update_session.commit()
            continue

        session_pending.append(
            {
                "id": str(approval.id),
                "agent_run_id": str(approval.agent_run_id),
                "tool_call": approval.tool_call,
                "status": approval.status,
                "created_at": approval.created_at.isoformat() if approval.created_at else None,
            }
        )

    if auto_rejected:
        logger.info("approvals.auto_rejected", count=len(auto_rejected), ids=auto_rejected)

    return session_pending


@router.get(
    "/pending",
    dependencies=[require_permission(Permission.APPROVALS_DECIDE)],
)
async def list_global_pending_approvals() -> list[dict[str, Any]]:
    """List ALL pending approvals for the caller's tenant, newest first."""
    tenant_id = get_tenant()
    if tenant_id is None:
        raise HTTPException(status_code=403, detail="No tenant context")

    async with async_session() as session:
        repo = TenantScopedRepository(session, Approval)
        all_pending = await repo.find(status="pending")

    result: list[dict[str, Any]] = []
    for approval in all_pending:
        if approval.tenant_id != tenant_id:
            continue
        tc = approval.tool_call or {}
        result.append({
            "id": str(approval.id),
            "agent_run_id": str(approval.agent_run_id),
            "tool_call": tc,
            "status": approval.status,
            "created_at": approval.created_at.isoformat() if approval.created_at else None,
        })

    result.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return result


@router.get(
    "/{approval_id}",
    dependencies=[require_permission(Permission.APPROVALS_DECIDE)],
)
async def get_approval(
    approval_id: uuid.UUID,
) -> dict[str, Any]:
    """Get the current status of a single approval."""
    async with async_session() as session:
        repo = TenantScopedRepository(session, Approval)
        approval = await repo.get(approval_id)

    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")

    # Defense-in-depth: verify tenant_id even though TenantScopedRepository
    # already scoped the query
    tenant_id = get_tenant()
    if tenant_id is not None and approval.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Approval not found")

    return {
        "id": str(approval.id),
        "agent_run_id": str(approval.agent_run_id),
        "tool_call": approval.tool_call,
        "status": approval.status,
        "created_at": approval.created_at.isoformat() if approval.created_at else None,
        "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
        "decision_payload": approval.decision_payload,
    }


@router.post(
    "/{approval_id}/decide",
    dependencies=[require_permission(Permission.APPROVALS_DECIDE)],
)
async def decide_approval(
    approval_id: uuid.UUID,
    decision: ApprovalAction,
    request: Request,
) -> dict[str, Any]:
    """Make a decision on a pending approval and resume the agent graph.

    The decision body is an ``ApprovalAction`` with the new shape:
    - ``action``: ``"approve"`` | ``"reject"`` | ``"edit"``
    - ``edited_inputs``: dict (required when action=edit)
    - ``comment``: optional human comment
    """
    # Resolve action from backward-compat fields
    if decision.action is not None:
        decision_action = decision.action
        edited_inputs = decision.edited_inputs
    else:
        decision_action = "approve" if decision.approved else "reject"
        edited_inputs = decision.modified_inputs

    if decision_action == "edit" and edited_inputs is None:
        raise HTTPException(
            status_code=400,
            detail="edited_inputs is required when action=edit",
        )

    # Load and verify the approval record
    async with async_session() as session:
        repo = TenantScopedRepository(session, Approval)
        approval = await repo.get(approval_id)

        if approval is None:
            raise HTTPException(status_code=404, detail="Approval not found")

        if approval.status != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"Approval is already {approval.status}",
            )

        # Explicit tenant check — do not rely solely on TenantScopedRepository
        tenant_id = get_tenant()
        if tenant_id is not None and approval.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403,
                detail="This approval does not belong to your tenant",
            )

        # Extract session_id from approval tool_call payload
        tool_call = approval.tool_call or {}
        session_id = tool_call.get("session_id")

        # Persist the decision
        resume_value: dict[str, Any] = {
            "action": decision_action,
            "edited_inputs": edited_inputs,
            "comment": decision.comment,
        }
        await repo.update(
            approval.id,
            status=decision_action,
            decided_at=datetime.now(UTC),
            decision_payload=resume_value,
        )
        await session.commit()

    # Resume the graph via checkpointer (cross-worker safe, no in-memory cache)
    if session_id:
        sid = str(session_id)
        try:
            graph = _build_graph_from_request(request)
            config = {"configurable": {"thread_id": sid}}
            async for _event in graph.astream(
                Command(resume=resume_value),
                config,
                stream_mode="updates",
            ):
                pass  # Consume all events
        except Exception as exc:
            err_msg = f"Failed to resume agent: {exc}"
            logger.error("approvals.resume_failed", approval_id=str(approval_id), error=err_msg)
            raise HTTPException(
                status_code=500,
                detail=err_msg,
            ) from exc

    return {
        "status": "ok",
        "approval_id": str(approval_id),
        "decision": decision_action,
    }
