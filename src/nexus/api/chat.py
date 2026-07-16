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

from starlette.requests import Request


def _get_tenant_id(request: Request) -> str:
    """Extract tenant_id from request state or middleware context."""
    from nexus.db.context import get_tenant  # noqa: PLC0415

    tid = getattr(request.state, "tenant_id", None)
    if tid is not None:
        return str(tid)
    ct = get_tenant()
    if ct is not None:
        return str(ct)
    return "00000000-0000-0000-0000-000000000001"


def _get_user_id(request: Request) -> str:
    """Extract user_id from request state."""
    uid = getattr(request.state, "user_id", None)
    if uid is not None:
        return str(uid)
    return "00000000-0000-0000-0000-000000000002"

import structlog
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from nexus.agent.runner import AgentEvent, AgentRunner
from nexus.api.dependencies import get_agent_runner
from nexus.api.schemas import ChatRequest, ChatResponse

logger = structlog.get_logger("nexus.api.chat")

router = APIRouter(prefix="/api/v1/sessions", tags=["chat"])

_HEARTBEAT_INTERVAL = 15  # seconds


async def _heartbeat_generator(
    event_aiter: AsyncIterator[AgentEvent],
) -> AsyncIterator[dict[str, Any]]:
    """Yield SSE events from *event_aiter*, interleaving keepalive comments.

    Sends a ``:keep-alive`` SSE comment every ``_HEARTBEAT_INTERVAL`` seconds
    so that proxies and browsers do not time out the connection.
    """
    done = False

    async def _drain() -> None:
        nonlocal done
        async for agent_event in event_aiter:
            yield agent_event
        done = True

    async def _heartbeat() -> None:
        while not done:
            await asyncio.sleep(_HEARTBEAT_INTERVAL)
            yield {"comment": "keep-alive"}

    ag = _drain()
    hb = _heartbeat()

    ag_task = asyncio.create_task(ag.__anext__())
    hb_task = asyncio.create_task(hb.__anext__())

    while not done:
        done_inner = done
        tasks = [ag_task, hb_task]
        if done_inner:
            tasks = [hb_task]

        done_set, _ = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )

        for t in done_set:
            try:
                result = t.result()
                if result is not None:
                    yield result
            except StopAsyncIteration:
                done = True
                break
            except Exception as exc:
                logger.error("chat.heartbeat_error", error=str(exc))
                done = True
                break

        if not done:
            ag_task = asyncio.create_task(ag.__anext__())
            hb_task = asyncio.create_task(hb.__anext__())

    # Cancel any pending tasks
    if not ag_task.done():
        ag_task.cancel()
    if not hb_task.done():
        hb_task.cancel()


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

    if body.stream:
        return _stream_response(runner, sid, tid, uid, body.message)
    return await _json_response(runner, sid, tid, uid, body.message)


def _stream_response(
    runner: AgentRunner,
    sid: str,
    tid: str,
    uid: str,
    message: str,
) -> EventSourceResponse:
    """Return an SSE streaming response with heartbeats."""

    async def _generate() -> AsyncIterator[dict[str, Any]]:
        event_aiter = runner.invoke(
            session_id=sid,
            user_message=message,
            tenant_id=tid,
            user_id=uid,
        )

        async for sse_event in _heartbeat_generator(event_aiter):
            # If it's a keepalive comment, yield as-is
            if "comment" in sse_event:
                yield sse_event
                continue

            # Otherwise it's an AgentEvent wrapped in a dict-like
            if isinstance(sse_event, AgentEvent):
                yield {"event": sse_event.type, "data": json.dumps(sse_event.to_dict())}
            else:
                yield sse_event

        # Signal completion
        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(_generate())


async def _json_response(
    runner: AgentRunner,
    sid: str,
    tid: str,
    uid: str,
    message: str,
) -> ChatResponse:
    """Collect all events and return as a single JSON response."""
    events: list[dict[str, Any]] = []
    final_text: str | None = None
    interrupted = False
    approval_payload: dict[str, Any] | None = None
    error: str | None = None

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

    return ChatResponse(
        session_id=sid,
        final_response=final_text,
        requires_approval=interrupted,
        approval_payload=approval_payload,
        interrupted=interrupted,
        error=error,
        events=events,
    )
