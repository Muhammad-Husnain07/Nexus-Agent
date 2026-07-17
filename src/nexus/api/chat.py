"""Chat SSE endpoint — stream agent events in real time via Server-Sent Events.

Provides a single ``POST /api/v1/sessions/{session_id}/chat`` endpoint that
accepts a user message and streams agent execution events back via SSE with
a 15-second heartbeat.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import structlog
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse
from starlette.requests import Request as StarletteRequest

from nexus.agent.runner import AgentEvent, AgentRunner
from nexus.api.dependencies import get_agent_runner
from nexus.api.schemas import ChatRequest, ChatResponse
from nexus.utils.constants import DEFAULT_TENANT_ID_STR, DEFAULT_USER_ID_STR

logger = structlog.get_logger("nexus.api.chat")

router = APIRouter(prefix="/sessions", tags=["chat"])

_HEARTBEAT_INTERVAL = 15


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

    runner: AgentRunner = get_agent_runner(request)
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
