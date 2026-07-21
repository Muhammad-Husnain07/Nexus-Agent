"""FastAPI router for /api/v1/approvals — structured HITL approval management."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import json as json_module

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from langgraph.types import Command
from sse_starlette.sse import EventSourceResponse

from nexus.agent.graph import build_agent_graph
from nexus.agent.runner import AgentEvent
from nexus.agent.schemas import ApprovalAction
from nexus.config.settings import get_settings
from nexus.db.base import async_session
from nexus.db.models.agent_run import Approval
from nexus.db.repositories.base import GenericRepository
from nexus.llm.client import LLMClient
from nexus.redis_client.client import get_redis_client
from nexus.redis_client.pubsub import EventBus

from nexus.tools.discovery import DynamicToolSelector
from nexus.tools.executor import ToolExecutor
from nexus.tools.registry import ToolRegistry

logger = structlog.get_logger("nexus.api.approvals")

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _build_graph_from_request(request: Request) -> Any:
    """Build a fresh compiled graph."""
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


async def _resume_generator(
    graph: Any,
    config: dict[str, Any],
    resume_value: dict[str, Any],
) -> Any:
    """Yield SSE events from a resumed graph execution."""
    try:
        async for event in graph.astream(
            Command(resume=resume_value),
            config,
            stream_mode="updates",
        ):
            if isinstance(event, AgentEvent):
                yield {"event": event.type, "data": json_module.dumps(event.to_dict())}
            else:
                yield {"event": "update", "data": json_module.dumps(event) if isinstance(event, dict) else str(event)}
    except Exception as exc:
        logger.error("approvals.resume_stream_error", error=str(exc))
        yield {"event": "error", "data": json_module.dumps({"message": "Failed to resume agent execution"})}
    yield {"event": "done", "data": "{}"}


@router.get("/pending/{session_id}")
async def list_pending_approvals(
    session_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Return all pending approvals for a session."""
    settings = get_settings().agent
    timeout_hours = settings.approval_timeout_hours
    cutoff = datetime.now(UTC) - timedelta(hours=timeout_hours)

    async with async_session() as session:
        repo = GenericRepository(session, Approval)
        all_pending: list[Approval] = await repo.find(status="pending")

    session_pending: list[dict[str, Any]] = []
    auto_rejected: list[str] = []
    for approval in all_pending:
        # Generic interrupt types store session_id in interrupt_payload
        payload = approval.interrupt_payload or {}
        tc = approval.tool_call or {}
        approval_session_id = (
            tc.get("session_id")
            or payload.get("session_id")
            or payload.get("config", {}).get("configurable", {}).get("thread_id")
        )
        if approval_session_id != str(session_id):
            continue

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
                "interrupt_type": approval.interrupt_type,
                "tool_call": approval.tool_call,
                "interrupt_payload": approval.interrupt_payload,
                "status": approval.status,
                "created_at": approval.created_at.isoformat() if approval.created_at else None,
            }
        )

    if auto_rejected:
        logger.info("approvals.auto_rejected", count=len(auto_rejected), ids=auto_rejected)

    return session_pending


@router.get("/pending")
async def list_global_pending_approvals() -> list[dict[str, Any]]:
    """List ALL pending approvals, newest first."""
    async with async_session() as session:
        repo = GenericRepository(session, Approval)
        all_pending = await repo.find(status="pending")

    result: list[dict[str, Any]] = []
    for approval in all_pending:
        tc = approval.tool_call or {}
        result.append({
            "id": str(approval.id),
            "agent_run_id": str(approval.agent_run_id),
            "interrupt_type": approval.interrupt_type,
            "tool_call": tc,
            "interrupt_payload": approval.interrupt_payload,
            "status": approval.status,
            "created_at": approval.created_at.isoformat() if approval.created_at else None,
        })

    result.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return result


@router.get("/{approval_id}")
async def get_approval(
    approval_id: uuid.UUID,
) -> dict[str, Any]:
    """Get the current status of a single approval."""
    async with async_session() as session:
        repo = GenericRepository(session, Approval)
        approval = await repo.get(approval_id)

    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")

    return {
        "id": str(approval.id),
        "agent_run_id": str(approval.agent_run_id),
        "interrupt_type": approval.interrupt_type,
        "tool_call": approval.tool_call,
        "interrupt_payload": approval.interrupt_payload,
        "status": approval.status,
        "created_at": approval.created_at.isoformat() if approval.created_at else None,
        "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
        "decision_payload": approval.decision_payload,
    }


@router.post("/{approval_id}/decide", response_model=None)
async def decide_approval(
    approval_id: uuid.UUID,
    decision: ApprovalAction,
    request: Request,
    stream: bool = Query(False, description="If true, returns SSE stream of resumed execution"),
):
    """Make a decision on a pending approval and resume the agent graph.

    When ``stream=true``, returns an SSE stream with tool_call_completed,
    final_response, and done events — same format as the chat endpoint.
    When ``stream=false`` (default), consumes events silently and returns JSON.
    """
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

    async with async_session() as session:
        repo = GenericRepository(session, Approval)
        approval = await repo.get(approval_id)

        if approval is None:
            raise HTTPException(status_code=404, detail="Approval not found")

        if approval.status != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"Approval is already {approval.status}",
            )

        tool_call = approval.tool_call or {}
        interrupt_payload = approval.interrupt_payload or {}
        # Resolve session_id from tool_call (legacy) or interrupt_payload (generic)
        session_id = (
            tool_call.get("session_id")
            or interrupt_payload.get("session_id")
            or interrupt_payload.get("config", {}).get("configurable", {}).get("thread_id")
        )

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

    if session_id and stream:
        sid = str(session_id)
        try:
            graph = _build_graph_from_request(request)
            config = {"configurable": {"thread_id": sid}}
            return EventSourceResponse(_resume_generator(graph, config, resume_value))
        except Exception as exc:
            err_msg = f"Failed to resume agent: {exc}"
            logger.error("approvals.resume_failed", approval_id=str(approval_id), error=err_msg)
            raise HTTPException(status_code=500, detail=err_msg) from exc
    elif session_id:
        sid = str(session_id)
        try:
            graph = _build_graph_from_request(request)
            config = {"configurable": {"thread_id": sid}}
            async for _event in graph.astream(
                Command(resume=resume_value),
                config,
                stream_mode="updates",
            ):
                pass
        except Exception as exc:
            err_msg = f"Failed to resume agent: {exc}"
            logger.error("approvals.resume_failed", approval_id=str(approval_id), error=err_msg)
            raise HTTPException(status_code=500, detail=err_msg) from exc

    return {
        "status": "ok",
        "approval_id": str(approval_id),
        "decision": decision_action,
    }
