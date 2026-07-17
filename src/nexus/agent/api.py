"""FastAPI router for /api/v1/agent — invoke, stream, approve, reject, edit."""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from sse_starlette.sse import EventSourceResponse

from nexus.agent import graph_cache
from nexus.agent.graph import build_agent_graph
from nexus.agent.runner import AgentRunner
from nexus.agent.schemas import (
    AgentInvokeRequest,
    AgentInvokeResponse,
    AgentResumeResponse,
    AgentStateResponse,
    ApprovalAction,
)
from nexus.agent.state import AgentState
from nexus.db.base import async_session
from nexus.db.models.agent_run import Approval
from nexus.db.repositories.base import GenericRepository
from nexus.llm.client import LLMClient
from nexus.redis_client.client import get_redis_client
from nexus.redis_client.pubsub import EventBus
from nexus.sessions.schemas import SessionCreate
from nexus.sessions.service import SessionService
from nexus.tools.discovery import DynamicToolSelector
from nexus.tools.executor import ToolExecutor
from nexus.tools.registry import ToolRegistry

logger = structlog.get_logger("nexus.agent.api")

router = APIRouter(prefix="/agent", tags=["agent"])

# ---------------------------------------------------------------------------
# Shared compiled graph cache lives in ``graph_cache`` module
# ---------------------------------------------------------------------------
_MAX_TITLE_LENGTH: int = 80


def _get_tenant_id(request: Request) -> uuid.UUID:
    """Extract tenant_id from request state or middleware context."""
    tid = getattr(request.state, "tenant_id", None)
    if tid is not None:
        return uuid.UUID(tid) if isinstance(tid, str) else tid
    from nexus.db.context import get_tenant  # noqa: PLC0415

    ct = get_tenant()
    if ct is not None:
        return ct
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


def _get_user_id(request: Request) -> uuid.UUID:
    """Extract user_id from request state."""
    uid = getattr(request.state, "user_id", None)
    if uid is not None:
        return uuid.UUID(uid) if isinstance(uid, str) else uid
    return uuid.UUID("00000000-0000-0000-0000-000000000002")


async def _get_session_service(request: Request) -> SessionService:
    """Build a SessionService wired via app state."""
    from nexus.config.settings import get_settings  # noqa: PLC0415
    from nexus.db.base import async_session  # noqa: PLC0415
    from nexus.sessions.context_window import ContextWindowManager  # noqa: PLC0415
    from nexus.sessions.repository import MessageRepository, SessionRepository  # noqa: PLC0415
    from nexus.sessions.system_prompt import SystemPromptBuilder  # noqa: PLC0415

    settings = get_settings()
    llm = LLMClient()
    session_maker = async_session
    async with session_maker() as db_session:
        return SessionService(
            session_repo=SessionRepository(db_session),
            message_repo=MessageRepository(db_session),
            context_window=ContextWindowManager(llm_client=llm, model=settings.llm.default_model),
            prompt_builder=SystemPromptBuilder(llm_client=llm),
            llm_client=llm,
            model=settings.llm.default_model,
        )


async def _ensure_session_exists(
    request: Request,
    session_id: uuid.UUID,
    user_message: str,
) -> None:
    """Create a session in the database if it doesn't exist yet."""
    try:
        service = await _get_session_service(request)
        existing = await service.get_session(session_id)
        if existing is None:
            ellipsis = "..." if len(user_message) > _MAX_TITLE_LENGTH else ""
            title = user_message[:_MAX_TITLE_LENGTH] + ellipsis
            await service.create_session(
                tenant_id=_get_tenant_id(request),
                user_id=_get_user_id(request),
                data=SessionCreate(title=title),
            )
    except Exception as exc:
        logger.warning("session.create_failed", session_id=str(session_id), error=str(exc))


async def _get_or_create_graph(
    session_id: str,
    request: Request,
) -> CompiledStateGraph:
    """Return the compiled graph for *session_id*, creating it if necessary."""
    existing = graph_cache.get_graph(session_id)
    if existing is not None:
        return existing

    settings = request.app.state.settings
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

    from nexus.db.base import async_session  # noqa: PLC0415
    from nexus.memory.checkpointer import get_checkpointer  # noqa: PLC0415

    checkpointer = None
    if settings.memory.checkpointer_type == "postgres":
        try:
            checkpointer = await get_checkpointer()
        except Exception as exc:
            logger.warning("checkpointer.unavailable", error=str(exc))

    graph = build_agent_graph(
        llm_client=llm,
        tool_selector=tool_selector,
        tool_executor=tool_executor,
        event_bus=event_bus,
        model=settings.llm.default_model,
        session_factory=async_session,
        checkpointer=checkpointer,
    )
    graph_cache.set_graph(session_id, graph)
    return graph


def _remove_graph(session_id: str) -> None:
    graph_cache.remove_graph(session_id)


def _make_config(session_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": session_id}}


async def _build_initial_state(
    session_id: str,
    user_message: str,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> AgentState:
    """Build the initial AgentState for a new agent invocation."""
    return {
        "messages": [{"role": "user", "content": user_message}],
        "tenant_id": tenant_id or "00000000-0000-0000-0000-000000000001",
        "session_id": session_id,
        "user_id": user_id or "00000000-0000-0000-0000-000000000002",
        "plan": None,
        "current_step_index": 0,
        "gathered_requirements": {},
        "available_tools": [],
        "pending_approval": None,
        "iteration_count": 0,
        "scratchpad": "",
        "tool_results": [],
        "final_response": None,
        "intent": None,
        "missing_info_slots": None,
        "errors": [],
        "_bound_tools": [],
        "intent_analysis": None,
        "analysis_result": None,
        "needs_human_review": False,
        "questions_asked": 0,
        "_routing_decision": "continue",
    }


async def _check_if_run_exists(
    graph: CompiledStateGraph,
    config: dict[str, Any],
    session_id: str,
) -> AgentStateResponse | None:
    """Check whether this session already has a run (paused/completed).

    Returns a snapshot if there is one, else None.
    """
    try:
        state_snapshot = await graph.aget_state(config)
    except Exception:
        return None

    if state_snapshot is not None and state_snapshot.next:
        pending = state_snapshot.values.get("pending_approval")
        fr = state_snapshot.values.get("final_response")
        return AgentStateResponse(
            session_id=uuid.UUID(session_id),
            status="paused" if pending else "running",
            current_node=state_snapshot.next[0] if state_snapshot.next else None,
            pending_approval=pending,
            final_response=fr,
        )
    return None


# ---------------------------------------------------------------------------
# Helper: translate LangGraph state updates to event dicts
# ---------------------------------------------------------------------------


def _translate_events(state_updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert a list of LangGraph state-update dicts into flat event dicts."""
    events: list[dict[str, Any]] = []
    for update in state_updates:
        for node_name, state_update in update.items():
            events.append(
                {
                    "node": node_name,
                    "update": {k: v for k, v in state_update.items() if v is not None},
                }
            )
    return events


def _extract_result(
    state_updates: list[dict[str, Any]],
) -> tuple[str | None, bool, dict[str, Any] | None]:
    """Extract final_response, interrupted flag, and approval_payload from updates."""
    final_response: str | None = None
    interrupted = False
    approval_payload: dict[str, Any] | None = None

    for update in state_updates:
        for _node_name, state_update in update.items():
            fr = state_update.get("final_response")
            if fr is not None:
                final_response = fr
            if state_update.get("pending_approval") is not None:
                interrupted = True
                approval_payload = state_update["pending_approval"]

    return final_response, interrupted, approval_payload


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/invoke", response_model=AgentInvokeResponse)
async def invoke_agent(
    data: AgentInvokeRequest,
    request: Request,
) -> AgentInvokeResponse:
    """Run the agent synchronously, collecting all events and returning the final result.

    If the session already has a paused run (e.g. awaiting approval), returns
    immediately with ``interrupted=True`` and the approval payload.
    """
    sid = str(data.session_id)
    graph = await _get_or_create_graph(sid, request)
    config = _make_config(sid)

    # Check for existing paused run
    existing = await _check_if_run_exists(graph, config, sid)
    if existing is not None:
        return AgentInvokeResponse(
            session_id=data.session_id,
            interrupted=existing.status == "paused",
            approval_payload=existing.pending_approval,
            events=[],
        )

    # Ensure a DB session record exists
    await _ensure_session_exists(request, data.session_id, data.message)

    tid = str(_get_tenant_id(request))
    uid = str(_get_user_id(request))
    initial = await _build_initial_state(sid, data.message, tenant_id=tid, user_id=uid)

    state_updates: list[dict[str, Any]] = []

    try:
        async for event in graph.astream(initial, config, stream_mode="updates"):
            state_updates.append(event)
    except Exception as exc:
        logger.error("agent.invoke.failed", session_id=sid, error=str(exc))
        _remove_graph(sid)
        return AgentInvokeResponse(
            session_id=data.session_id,
            error=str(exc),
        )

    final_response, interrupted, approval_payload = _extract_result(state_updates)
    events = _translate_events(state_updates)

    return AgentInvokeResponse(
        session_id=data.session_id,
        final_response=final_response,
        interrupted=interrupted,
        approval_payload=approval_payload,
        events=events,
    )


@router.post("/stream")
async def stream_agent(
    data: AgentInvokeRequest,
    request: Request,
) -> EventSourceResponse:
    """Invoke the agent and stream events via Server-Sent Events.

    Events are sent as SSE with ``event`` and ``data`` fields matching
    ``AgentStreamEvent``.  An ``interrupt`` event is sent if the graph
    pauses for HITL approval.
    """
    sid = str(data.session_id)
    graph = await _get_or_create_graph(sid, request)
    config = _make_config(sid)

    # Check for existing paused run
    existing = await _check_if_run_exists(graph, config, sid)
    if existing is not None:
        return EventSourceResponse(
            [
                {
                    "event": existing.status,
                    "data": json.dumps(
                        {
                            "session_id": sid,
                            "pending_approval": existing.pending_approval,
                            "current_node": existing.current_node,
                        }
                    ),
                }
            ]
        )

    await _ensure_session_exists(request, data.session_id, data.message)

    tid = str(_get_tenant_id(request))
    uid = str(_get_user_id(request))
    initial = await _build_initial_state(sid, data.message, tenant_id=tid, user_id=uid)

    async def _event_generator() -> Any:
        try:
            async for event in graph.astream(initial, config, stream_mode="updates"):
                node_name = next(iter(event))
                state_update = event[node_name]

                for agent_event in AgentRunner._translate(node_name, state_update):
                    yield {
                        "event": agent_event.type,
                        "data": json.dumps(agent_event.to_dict()),
                    }

                # Detect interrupt for HITL approval
                if state_update.get("pending_approval") is not None:
                    yield {
                        "event": "interrupt",
                        "data": json.dumps(
                            {
                                "type": "approval_required",
                                "session_id": sid,
                                "payload": state_update["pending_approval"],
                            }
                        ),
                    }
                    return

            # Signal completion
            yield {"event": "done", "data": "{}"}

        except Exception as exc:
            logger.error("agent.stream.failed", session_id=sid, error=str(exc))
            yield {"event": "error", "data": json.dumps({"message": str(exc)})}

    return EventSourceResponse(_event_generator())


@router.post("/{session_id}/resume", response_model=AgentResumeResponse)
async def resume_agent(
    session_id: uuid.UUID,
    action: ApprovalAction,
    request: Request,
) -> AgentResumeResponse:
    """Resume an interrupted agent run with an approval decision.

    This is the generic resume endpoint used by approve, reject, and edit
    operations.  The caller provides ``approved`` and optionally
    ``modified_inputs`` to alter the tool call parameters before execution.
    """
    sid = str(session_id)
    graph = graph_cache.get_graph(sid)
    if graph is None:
        raise HTTPException(
            status_code=404,
            detail="No active agent run found for this session",
        )

    config = _make_config(sid)

    # Verify there is a paused run to resume
    snapshot = await graph.aget_state(config)
    if not snapshot.next:
        raise HTTPException(
            status_code=400,
            detail="Agent run is not paused; no interrupt to resume",
        )

    logger.info(
        "agent.resume",
        session_id=sid,
        approved=action.approved,
        has_modified=action.modified_inputs is not None,
    )

    # Map backward-compat fields to the new decision shape
    if action.action is not None:
        decision_action = action.action
        edited_inputs = action.edited_inputs
    else:
        decision_action = "approve" if action.approved else "reject"
        edited_inputs = action.modified_inputs

    resume_value: dict[str, Any] = {
        "action": decision_action,
        "edited_inputs": edited_inputs,
        "comment": action.comment,
    }

    state_updates: list[dict[str, Any]] = []

    # Persist Approval record before resuming
    try:
        async with async_session() as session:
            repo = GenericRepository(session, Approval)
            await repo.create(
                status=decision_action,
                agent_run_id=uuid.uuid4(),
                tool_call={},
                decision_payload=resume_value,
            )
            await session.commit()
    except Exception as exc:
        logger.warning("agent.approval_persist_failed", session_id=sid, error=str(exc))

    try:
        async for event in graph.astream(
            Command(resume=resume_value),
            config,
            stream_mode="updates",
        ):
            state_updates.append(event)
    except Exception as exc:
        logger.error("agent.resume.failed", session_id=sid, error=str(exc))
        # On resume failure the graph likely errored; clean up
        _remove_graph(sid)
        return AgentResumeResponse(
            session_id=session_id,
            status="error",
            error=str(exc),
        )

    final_response, interrupted, approval_payload = _extract_result(state_updates)

    if interrupted:
        # Run paused again — keep graph in cache
        return AgentResumeResponse(
            session_id=session_id,
            status="interrupted",
            final_response=final_response,
            requires_approval=True,
            approval_payload=approval_payload,
        )

    # Run completed — clean up graph cache
    _remove_graph(sid)
    return AgentResumeResponse(
        session_id=session_id,
        status="completed",
        final_response=final_response,
    )


@router.post("/{session_id}/approve", response_model=AgentResumeResponse)
async def approve_tool(
    session_id: uuid.UUID,
    request: Request,
) -> AgentResumeResponse:
    """Approve a pending tool call and resume execution."""
    return await resume_agent(
        session_id,
        ApprovalAction(action="approve"),
        request,
    )


@router.post("/{session_id}/reject", response_model=AgentResumeResponse)
async def reject_tool(
    session_id: uuid.UUID,
    request: Request,
) -> AgentResumeResponse:
    """Reject a pending tool call and resume execution (tool is skipped)."""
    return await resume_agent(
        session_id,
        ApprovalAction(action="reject"),
        request,
    )


@router.post("/{session_id}/edit", response_model=AgentResumeResponse)
async def edit_tool(
    session_id: uuid.UUID,
    action: ApprovalAction,
    request: Request,
) -> AgentResumeResponse:
    """Approve a pending tool call with modified input parameters."""
    edited = action.edited_inputs or action.modified_inputs
    if edited is None:
        raise HTTPException(
            status_code=400,
            detail="edited_inputs is required when editing a tool call",
        )
    return await resume_agent(
        session_id,
        ApprovalAction(action="edit", edited_inputs=edited),
        request,
    )


@router.get("/{session_id}/state", response_model=AgentStateResponse)
async def get_agent_state(
    session_id: uuid.UUID,
    request: Request,
) -> AgentStateResponse:
    """Get the current state of an agent run for a session."""
    sid = str(session_id)
    graph = graph_cache.get_graph(sid)
    if graph is None:
        raise HTTPException(
            status_code=404,
            detail="No active agent run found for this session",
        )

    config = _make_config(sid)

    try:
        state_snapshot = await graph.aget_state(config)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve agent state: {exc}",
        ) from exc

    pending = state_snapshot.values.get("pending_approval")
    fr = state_snapshot.values.get("final_response")

    if not state_snapshot.next:
        status = "completed"
    elif pending:
        status = "paused"
    else:
        status = "running"

    return AgentStateResponse(
        session_id=session_id,
        status=status,
        current_node=state_snapshot.next[0] if state_snapshot.next else None,
        pending_approval=pending,
        final_response=fr,
    )
