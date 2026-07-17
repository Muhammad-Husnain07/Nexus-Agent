"""Chat SSE endpoint — stream agent events in real time via Server-Sent Events.

Provides ``POST /sessions/{session_id}/chat`` for invoking the agent,
and ``GET /sessions/{session_id}/state`` for inspecting checkpoint state.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse
from starlette.requests import Request as StarletteRequest

from nexus.agent.runner import AgentEvent, AgentRunner
from nexus.agent.schemas import AgentStateResponse
from nexus.api.dependencies import get_agent_runner
from nexus.api.schemas import ChatRequest, ChatResponse
from nexus.utils.constants import DEFAULT_TENANT_ID_STR, DEFAULT_USER_ID_STR

logger = structlog.get_logger("nexus.api.chat")

router = APIRouter(prefix="/sessions", tags=["chat"])

_HEARTBEAT_INTERVAL = 15
_MAX_TITLE_LENGTH: int = 80


async def _ensure_session_exists(
    request: Request,
    session_id: uuid.UUID,
    user_message: str,
) -> None:
    """Create a session in the database if it doesn't exist yet.

    Uses its own DB session with explicit commit to ensure the row
    persists before the agent's tool executor writes ``ToolExecution``
    rows that reference it.
    """
    from nexus.db.base import async_session  # noqa: PLC0415
    from nexus.db.context import get_tenant  # noqa: PLC0415
    from nexus.sessions.repository import SessionRepository  # noqa: PLC0415

    try:
        async with async_session() as db_session:
            repo = SessionRepository(db_session)
            existing = await repo.get(session_id)
            if existing is None:
                ellipsis = "..." if len(user_message) > _MAX_TITLE_LENGTH else ""
                title = user_message[:_MAX_TITLE_LENGTH] + ellipsis
                tid = getattr(request.state, "tenant_id", None)
                if tid is None:
                    tid = get_tenant()
                uid = getattr(request.state, "user_id", None)
                if uid is None:
                    uid = uuid.UUID(DEFAULT_USER_ID_STR)
                await repo.create(
                    id=session_id,
                    tenant_id=uuid.UUID(str(tid)) if isinstance(tid, str) else tid,
                    user_id=uuid.UUID(str(uid)) if isinstance(uid, str) else uid,
                    title=title,
                )
                await db_session.commit()
                logger.info("session_created_for_agent", session_id=str(session_id))
    except Exception as exc:
        logger.warning("session.create_failed", session_id=str(session_id), error=str(exc))


def _get_tenant_id(request: StarletteRequest) -> str:
    """Extract tenant_id from request state or middleware context."""
    from nexus.db.context import get_tenant  # noqa: PLC0415

    tid = getattr(request.state, "tenant_id", None)
    if tid is not None:
        return str(tid)
    ct = get_tenant()
    if ct is not None:
        return str(ct)
    return DEFAULT_TENANT_ID_STR


def _get_user_id(request: StarletteRequest) -> str:
    """Extract user_id from request state."""
    uid = getattr(request.state, "user_id", None)
    if uid is not None:
        return str(uid)
    return DEFAULT_USER_ID_STR


async def _heartbeat_generator(
    event_aiter: AsyncIterator[AgentEvent],
) -> AsyncIterator[dict[str, Any]]:
    """Yield SSE events from *event_aiter*, interleaving keepalive comments.

    Uses ``asyncio.wait_for`` with a timeout to send a ``:keep-alive`` SSE
    comment every ``_HEARTBEAT_INTERVAL`` seconds while waiting for the
    next agent event.
    """
    aiter = event_aiter.__aiter__()

    while True:
        try:
            event = await asyncio.wait_for(
                aiter.__anext__(),
                timeout=_HEARTBEAT_INTERVAL,
            )
            if isinstance(event, AgentEvent):
                yield {"event": event.type, "data": json.dumps(event.to_dict())}
            else:
                yield event
        except TimeoutError:
            yield {"comment": "keep-alive"}
        except StopAsyncIteration:
            break
        except Exception as exc:
            logger.error("chat.heartbeat_error", error=str(exc))
            break


@router.post("/{session_id}/chat", response_model=None)
async def chat(
    session_id: uuid.UUID,
    body: ChatRequest,
    request: Request,
) -> EventSourceResponse | ChatResponse:
    """Send a message to the agent and receive events via SSE or JSON.

    If ``body.stream`` is ``True`` (default), returns an SSE stream with
    ``15s`` keepalive heartbeats.  Event types include:
    ``plan_created``, ``tool_call_started``, ``tool_call_completed``,
    ``clarification_needed``, ``approval_required``, ``intermediate_preview``,
    ``final_response``, ``error``, ``done``.

    If ``body.stream`` is ``False``, returns a single ``ChatResponse`` JSON
    body with all events accumulated.
    """
    sid = str(session_id)
    uid = _get_user_id(request)
    tid = _get_tenant_id(request)

    # Ensure a DB session record exists before tool execution writes to it
    await _ensure_session_exists(request, session_id, body.message)

    runner: AgentRunner = await get_agent_runner(request)
    app_state = request.app.state

    if body.stream:
        return _stream_response(runner, sid, tid, uid, body.message, app_state)
    return await _json_response(runner, sid, tid, uid, body.message, app_state)



def _stream_response(
    runner: AgentRunner,
    sid: str,
    tid: str,
    uid: str,
    message: str,
    app_state: Any = None,
) -> EventSourceResponse:
    """Return an SSE streaming response with heartbeats and shutdown tracking."""

    conn_id = str(uuid.uuid4())
    if app_state is not None:
        if not hasattr(app_state, "active_sse_connections"):
            app_state.active_sse_connections = set()
        app_state.active_sse_connections.add(conn_id)
        app_state.active_agent_runs = getattr(app_state, "active_agent_runs", 0) + 1

    async def _generate() -> AsyncIterator[dict[str, Any]]:
        try:
            event_aiter = runner.invoke(
                session_id=sid,
                user_message=message,
                tenant_id=tid,
                user_id=uid,
            )

            async for sse_event in _heartbeat_generator(event_aiter):
                yield sse_event

            yield {"event": "done", "data": "{}"}
        finally:
            if app_state is not None:
                app_state.active_agent_runs = max(0, getattr(app_state, "active_agent_runs", 1) - 1)
                app_state.active_sse_connections.discard(conn_id)

    return EventSourceResponse(_generate())


async def _json_response(
    runner: AgentRunner,
    sid: str,
    tid: str,
    uid: str,
    message: str,
    app_state: Any = None,
) -> ChatResponse:
    """Collect all events and return as a single JSON response."""
    events: list[dict[str, Any]] = []
    final_text: str | None = None
    interrupted = False
    approval_payload: dict[str, Any] | None = None
    error: str | None = None

    if app_state is not None:
        app_state.active_agent_runs = getattr(app_state, "active_agent_runs", 0) + 1

    try:
        async for agent_event in runner.invoke(
            session_id=sid,
            user_message=message,
            tenant_id=tid,
            user_id=uid,
        ):
            if agent_event.type == "final_response":
                final_text = agent_event.payload.get("text")
            elif agent_event.type == "approval_required":
                interrupted = True
                approval_payload = agent_event.payload
            elif agent_event.type == "error":
                error = agent_event.payload.get("message") or agent_event.payload.get("errors", [""])[0]

            events.append(agent_event.to_dict())
    finally:
        if app_state is not None:
            app_state.active_agent_runs = max(0, getattr(app_state, "active_agent_runs", 1) - 1)

    return ChatResponse(
        session_id=sid,
        final_response=final_text,
        requires_approval=interrupted,
        approval_payload=approval_payload,
        interrupted=interrupted,
        error=error,
        events=events,
    )


@router.get("/{session_id}/state")
async def get_session_state(
    session_id: uuid.UUID,
    request: Request,
) -> AgentStateResponse:
    """Get the current state of an agent run for a session.

    Returns run status, pending approvals, and the final response.
    Returns 404 if no state exists for the session.
    """
    sid = str(session_id)
    runner: AgentRunner = await get_agent_runner(request)
    graph = runner._build_graph()
    config = {"configurable": {"thread_id": sid}}

    try:
        state_snapshot = await graph.aget_state(config)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve agent state: {exc}",
        ) from exc

    if not state_snapshot.values.get("messages"):
        raise HTTPException(
            status_code=404,
            detail="No agent run found for this session",
        )

    pending = state_snapshot.values.get("pending_approval")
    fr = state_snapshot.values.get("final_response")
    next_nodes = state_snapshot.next or []

    if not next_nodes:
        status = "completed"
    elif pending:
        status = "paused"
    else:
        status = "running"

    return AgentStateResponse(
        session_id=session_id,
        status=status,
        current_node=next_nodes[0] if next_nodes else None,
        pending_approval=pending,
        final_response=fr,
    )
