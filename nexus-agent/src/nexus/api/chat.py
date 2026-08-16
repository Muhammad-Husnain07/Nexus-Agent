"""Chat SSE endpoint — stream agent events in real time via Server-Sent Events.

Provides ``POST /sessions/{session_id}/chat`` for invoking the agent,
and ``GET /sessions/{session_id}/state`` for inspecting checkpoint state.
"""

from __future__ import annotations

import asyncio
import contextlib
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
    """Create a session in the database if it doesn't exist yet.

    C3/P0-C tenant isolation: the session is stamped with the verified
    caller's user_id; an existing session owned by another identity is
    rejected with 403 (legacy NULL-owner rows remain open).
    """
    from nexus.db.base import async_session  # noqa: PLC0415
    from nexus.security.ownership import identity_from_request, session_owner_ok  # noqa: PLC0415
    from nexus.sessions.repository import SessionRepository  # noqa: PLC0415

    identity = identity_from_request(request)
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
                    user_id=identity.user_id,
                )
                await db_session.commit()
                logger.info("session_created_for_agent", session_id=str(session_id))
            elif not session_owner_ok(identity, existing):
                raise HTTPException(
                    status_code=403,
                    detail="This session belongs to another user",
                )
    except HTTPException:
        raise
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
    ``clarification_needed``, ``approval_checkpoint``, ``intermediate_preview``,
    ``final_response``, ``error``, ``done``.

    If ``body.stream`` is ``False``, returns a single ``ChatResponse`` JSON
    body with all events accumulated.
    """
    sid = str(session_id)

    await _ensure_session_exists(request, session_id, body.message)

    runner: AgentRunner = await get_agent_runner(request)
    app_state = request.app.state

    # C3/P0-C: verified identity rides into the graph for the executor's
    # authorization gate (roles) — populated by the auth middleware only.
    from nexus.security.ownership import identity_from_request  # noqa: PLC0415

    user_context = identity_from_request(request).to_dict()

    # P2-B: the request correlation id (RequestIDMiddleware) is persisted
    # with the invocation outcome — every answer is traceable to the
    # HTTP request that produced it.
    req_id = getattr(request.state, "request_id", None)

    if body.stream:
        return _stream_response(runner, sid, body.message, app_state, user_context, req_id)
    return await _json_response(runner, sid, body.message, app_state, user_context, req_id)



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


def _stream_response(  # noqa: PLR0913
    runner: AgentRunner,
    sid: str,
    message: str,
    app_state: Any = None,
    user_context: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> EventSourceResponse:
    """Return an SSE streaming response with heartbeats and shutdown tracking.

    FE Step 2 (browser is disposable): the RUN is decoupled from the
    observer. ``runner.invoke`` executes in a detached task; this handler
    only observes its events through a queue. A client disconnect cancels
    the OBSERVER, never the run — the refreshed browser reconstructs the
    in-flight run via ``GET /sessions/{id}/state``.
    """

    conn_id = str(uuid.uuid4())
    if app_state is not None:
        if not hasattr(app_state, "active_sse_connections"):
            app_state.active_sse_connections = set()
        app_state.active_sse_connections.add(conn_id)
        app_state.active_agent_runs = getattr(app_state, "active_agent_runs", 0) + 1

    async def _generate() -> AsyncIterator[dict[str, Any]]:
        # Bounded queue: backpressure to the run when the observer is slow;
        # the run itself never blocks on a dead observer.
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=500)
        # Deliberately unreferenced after creation: the run is detached and
        # must survive the observer (the loop keeps it alive while running).
        _run_task = asyncio.create_task(
            _drain_invoke(
                runner.invoke(
                    session_id=sid,
                    user_message=message,
                    user_context=user_context,
                    request_id=request_id,
                ),
                queue,
                sid,
                message,
            )
        )
        try:
            async for sse_event in _heartbeat_generator(_QueueIterator(queue)):
                yield sse_event
            yield {"event": "done", "data": "{}"}
        except asyncio.CancelledError:
            # Observer disconnected — the run keeps executing server-side;
            # state is reconstructable via GET /state.
            logger.info("sse.observer_disconnected", session_id=sid)
        except Exception as exc:
            logger.error("sse.stream_error", session_id=sid, error=str(exc))
            with contextlib.suppress(Exception):
                yield {"event": "error", "data": json.dumps({"message": str(exc)})}
        finally:
            if app_state is not None:
                app_state.active_agent_runs = max(0, getattr(app_state, "active_agent_runs", 1) - 1)
                app_state.active_sse_connections.discard(conn_id)

    return EventSourceResponse(
        _generate(),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


class _QueueIterator:
    """Adapt an asyncio.Queue of events (None = end) into an async iterator."""

    def __init__(self, queue: asyncio.Queue[Any]) -> None:
        self._queue = queue

    def __aiter__(self) -> _QueueIterator:
        return self

    async def __anext__(self) -> Any:
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        return item


async def _drain_invoke(
    event_aiter: AsyncIterator[AgentEvent],
    queue: asyncio.Queue[Any],
    sid: str,
    message: str,
) -> None:
    """Drain the invocation into the observer queue.

    Runs detached: message persistence happens when the RUN finishes, not
    when the observer disconnects (a refreshed browser never loses the
    conversation record).
    """
    final_text: str | None = None
    try:
        async for event in event_aiter:
            if isinstance(event, AgentEvent):
                payload = event.payload or {}
                if event.type == "final_response" and payload.get("text"):
                    final_text = payload["text"]
            await queue.put(event)
    except Exception as exc:
        logger.error("sse.run_error", session_id=sid, error=str(exc))
        with contextlib.suppress(Exception):
            await queue.put({"event": "error", "data": json.dumps({"message": str(exc)})})
    finally:
        with contextlib.suppress(Exception):
            asyncio.ensure_future(_persist_messages(sid, message, final_text))
        with contextlib.suppress(Exception):
            await queue.put(None)


async def _json_response(
    runner: AgentRunner,
    sid: str,
    message: str,
    app_state: Any = None,
    user_context: dict[str, Any] | None = None,
    request_id: str | None = None,
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
            user_context=user_context,
            request_id=request_id,
        ):
            if agent_event.type == "final_response":
                final_text = agent_event.payload.get("text")
            elif agent_event.type == "approval_checkpoint":
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


@router.post("/{session_id}/cancel")
async def cancel_session_run(session_id: uuid.UUID, request: Request) -> dict[str, Any]:
    """FE Step 2: cooperatively cancel an in-flight run for a session.

    Sets the durable cancel flag (nexus:cancel:agent_run:{sid}); the runner
    checks it between node events and cancels itself (the run is decoupled
    from the SSE observer, so a Stop must cancel the RUN, not the observer).
    """
    from nexus.security.ownership import require_session_access  # noqa: PLC0415

    await require_session_access(request, session_id)

    from nexus.redis_client.client import get_redis_client  # noqa: PLC0415

    redis = get_redis_client()
    if redis is not None:
        try:
            await redis.set(
                f"nexus:cancel:agent_run:{session_id}", "1", ex=600,
            )
        except Exception as exc:
            logger.warning("chat.cancel_flag_failed", error=str(exc)[:200])
    logger.info("chat.cancel_requested", session_id=str(session_id))
    return {"cancelled": True}


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

    # C3/P0-C: a session's state is only readable by its owner.
    from nexus.security.ownership import require_session_access  # noqa: PLC0415

    await require_session_access(request, session_id)

    runner: AgentRunner = await get_agent_runner(request)
    graph = await runner._build_graph()
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

    status = derive_run_status(
        bool(next_nodes),
        state_snapshot.values.get("_invocation_status"),
    )

    return AgentStateResponse(
        session_id=session_id,
        status=status,
        current_node=next_nodes[0] if next_nodes else None,
        final_response=fr,
        approval_pending=_approval_pending_read_model(state_snapshot.values),
    )


def _approval_pending_read_model(values: dict[str, Any]) -> dict[str, Any] | None:
    """FE Step 1.5: expose an OPEN approval checkpoint as a read model.

    The server owns the approval (binding + expiry); a refreshed browser
    reconstructs the approval UX from this snapshot — never from client
    memory. Sanitized: the internal ``operation_hash`` is NOT exposed.
    Returns None when no approval is pending.
    """
    pending = values.get("_approval_pending")
    if not isinstance(pending, dict) or not pending:
        return None
    try:
        from nexus.agent.nodes.approval_checkpoint_resume_node import (  # noqa: PLC0415
            _approval_expired,
        )

        requested_at = pending.get("requested_at")
        expires_at: float | None = None
        if isinstance(requested_at, (int, float)) and requested_at > 0:
            from nexus.config.settings import get_settings  # noqa: PLC0415

            expires_at = float(requested_at) + float(
                get_settings().agent.approval_expiry_s
            )
        return {
            "policy": str(pending.get("policy") or ""),
            "step": str(pending.get("step") or ""),
            "message": str(pending.get("message") or ""),
            "context": str(pending.get("context") or ""),
            "tools": [str(t) for t in (pending.get("tools") or [])],
            "tool_details": pending.get("tool_details") or {},
            "requested_at": requested_at,
            "expires_at": expires_at,
            "expired": _approval_expired(pending),
        }
    except Exception:
        return None


def derive_run_status(has_next: bool, invocation_status: str | None) -> str:
    """D2/P0-D (I6): map the checkpoint to a truthful run status.

    A terminal-abnormal marker (crashed / timed-out / interrupted /
    failed) is reported as-is — never as a forever-"running" run. A
    completed marker (or an empty graph with no marker) is "completed".
    """
    from nexus.agent.runner import _TERMINAL_ABNORMAL

    if invocation_status in _TERMINAL_ABNORMAL:
        return invocation_status.lower()
    if invocation_status == "COMPLETED" or not has_next:
        return "completed"
    return "running"

