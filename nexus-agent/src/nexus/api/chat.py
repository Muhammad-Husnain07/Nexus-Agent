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

logger = structlog.get_logger("nexus.api.chat")

router = APIRouter(prefix="/sessions", tags=["chat"])

_HEARTBEAT_INTERVAL = 10
_MAX_TITLE_LENGTH: int = 80


async def _ensure_session_exists(
    request: Request,
    session_id: uuid.UUID,
    user_message: str,
) -> None:
    """Create a session in the database if it doesn't exist yet."""
    from nexus.db.base import async_session  # noqa: PLC0415
    from nexus.sessions.repository import SessionRepository  # noqa: PLC0415

    try:
        async with async_session() as db_session:
            repo = SessionRepository(db_session)
            existing = await repo.get(session_id)
            if existing is None:
                ellipsis = "..." if len(user_message) > _MAX_TITLE_LENGTH else ""
                title = user_message[:_MAX_TITLE_LENGTH] + ellipsis
                await repo.create(
                    id=session_id,
                    title=title,
                )
                await db_session.commit()
                logger.info("session_created_for_agent", session_id=str(session_id))
    except Exception as exc:
        logger.warning("session.create_failed", session_id=str(session_id), error=str(exc))





async def _heartbeat_generator(
    event_aiter: AsyncIterator[AgentEvent],
) -> AsyncIterator[dict[str, Any]]:
    """Yield SSE events from *event_aiter*, interleaving keepalive comments.

    Uses ``asyncio.wait`` with ``FIRST_COMPLETED`` to avoid cancelling the
    underlying ``__anext__()`` task on heartbeat timeout — unlike
    ``asyncio.wait_for`` which would cancel the agent graph execution.
    """
    aiter = event_aiter.__aiter__()
    next_event_task: asyncio.Task[AgentEvent] | None = None

    while True:
        if next_event_task is None:
            next_event_task = asyncio.create_task(aiter.__anext__())

        sleep_task = asyncio.create_task(asyncio.sleep(_HEARTBEAT_INTERVAL))
        done, pending = await asyncio.wait(
            [next_event_task, sleep_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        if next_event_task in done:
            sleep_task.cancel()
            try:
                event = next_event_task.result()
            except StopAsyncIteration:
                break
            except Exception as exc:
                logger.error("chat.heartbeat_error", error=str(exc))
                break

            next_event_task = None  # ready for next iteration
            if isinstance(event, AgentEvent):
                yield {"event": event.type, "data": json.dumps(event.to_dict())}
            else:
                yield event
        else:
            # Timeout fired — send heartbeat, keep next_event_task alive
            sleep_task.cancel()
            yield {"comment": "keep-alive"}


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

    await _ensure_session_exists(request, session_id, body.message)

    runner: AgentRunner = await get_agent_runner(request)
    app_state = request.app.state

    if body.stream:
        return _stream_response(runner, sid, body.message, app_state)
    return await _json_response(runner, sid, body.message, app_state)



async def _persist_messages(sid: str, user_message: str, assistant_text: str | None) -> None:
    """Save user and assistant messages to the Message table."""
    from nexus.db.base import async_session  # noqa: PLC0415
    from nexus.sessions.repository import MessageRepository  # noqa: PLC0415

    try:
        async with async_session() as db_session:
            repo = MessageRepository(db_session)
            await repo.create(
                session_id=uuid.UUID(sid),
                role="user",
                content={"text": user_message},
            )
            if assistant_text:
                await repo.create(
                    session_id=uuid.UUID(sid),
                    role="assistant",
                    content={"text": assistant_text},
                )
            await db_session.commit()
    except Exception as exc:
        logger.warning("message.persist_failed", session_id=sid, error=str(exc))


def _stream_response(
    runner: AgentRunner,
    sid: str,
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
        final_text: str | None = None
        try:
            event_aiter = runner.invoke(
                session_id=sid,
                user_message=message,
            )

            async for sse_event in _heartbeat_generator(event_aiter):
                # Capture final response text for persistence
                if sse_event.get("event") == "final_response":
                    try:
                        import json as _json
                        payload = _json.loads(sse_event.get("data", "{}"))
                        payload_data = payload.get("payload", {})
                        if payload_data.get("text"):
                            final_text = payload_data["text"]
                    except Exception:
                        pass
                yield sse_event

            yield {"event": "done", "data": "{}"}
        except asyncio.CancelledError:
            logger.info("sse.stream_cancelled", session_id=sid)
        except Exception as exc:
            logger.error("sse.stream_error", session_id=sid, error=str(exc))
            try:
                yield {"event": "error", "data": json.dumps({"message": str(exc)})}
            except Exception:
                pass
        finally:
            if app_state is not None:
                app_state.active_agent_runs = max(0, getattr(app_state, "active_agent_runs", 1) - 1)
                app_state.active_sse_connections.discard(conn_id)
            # Persist messages asynchronously after stream ends
            asyncio.ensure_future(_persist_messages(sid, message, final_text))

    return EventSourceResponse(
        _generate(),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _json_response(
    runner: AgentRunner,
    sid: str,
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

    # Persist messages to DB
    asyncio.ensure_future(_persist_messages(sid, message, final_text))

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

    fr = state_snapshot.values.get("final_response")
    next_nodes = state_snapshot.next or []

    status = "completed" if not next_nodes else "running"

    return AgentStateResponse(
        session_id=session_id,
        status=status,
        current_node=next_nodes[0] if next_nodes else None,
        final_response=fr,
    )
