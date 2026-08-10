"""WebSocket endpoint for bidirectional agent communication."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from nexus.agent.runner import AgentRunner
from nexus.llm.client import LLMClient
from nexus.redis_client.client import get_redis_client
from nexus.redis_client.pubsub import EventBus
from nexus.tools.executor import ToolExecutor
from nexus.tools.registry import ToolRegistry

logger = structlog.get_logger("nexus.api.websocket")
router = APIRouter(prefix="/sessions", tags=["chat"])

_HEARTBEAT_INTERVAL_S: float = 30.0
_HEARTBEAT_TIMEOUT_S: float = 10.0


@router.websocket("/{session_id}/ws")
async def handle_websocket(websocket: WebSocket) -> None:
    """Accept a WebSocket connection, run the agent, and stream events.

    The client sends JSON messages and receives a stream of ``AgentEvent``
    dicts.

    C3/P0-C: the connection is authenticated BEFORE ``accept()`` and the
    requested session must belong to the verified identity.
    """
    from nexus.config.settings import get_settings  # noqa: PLC0415
    from nexus.providers.auth import get_auth_provider  # noqa: PLC0415
    from nexus.security.ownership import session_owner_ok  # noqa: PLC0415

    _ws_settings = get_settings()
    session_id = websocket.path_params.get("session_id", str(uuid.uuid4()))
    sid = str(session_id)

    # 1. AUTHENTICATE before accepting — a rejected handshake never
    # establishes a connection.
    provider = get_auth_provider()
    headers = {k.lower(): v for k, v in websocket.headers.items()}
    _token = websocket.query_params.get("token")
    if _token and "authorization" not in headers:
        headers["authorization"] = f"Bearer {_token}"
    identity = None
    try:
        identity = await provider.authenticate(headers)
    except Exception as exc:
        logger.warning("websocket.auth_error", session_id=sid, error=str(exc)[:200])
    if identity is None and _ws_settings.auth.mode != "none":
        logger.info("websocket.auth_rejected", session_id=sid)
        await websocket.close(code=4401)
        return

    # 2. Session ownership (create-on-demand, stamped with the identity).
    from nexus.db.base import async_session as _ws_db  # noqa: PLC0415
    from nexus.sessions.repository import SessionRepository  # noqa: PLC0415

    try:
        async with _ws_db() as db_session:
            repo = SessionRepository(db_session)
            existing = await repo.get(uuid.UUID(sid))
            if existing is None:
                await repo.create(
                    id=uuid.UUID(sid),
                    title="WebSocket session",
                    user_id=identity.user_id if identity else "anonymous",
                )
                await db_session.commit()
            elif identity is None or not session_owner_ok(identity, existing):
                logger.info("websocket.ownership_rejected", session_id=sid)
                await websocket.close(code=4403)
                return
    except Exception as exc:
        logger.warning("websocket.session_check_failed", session_id=sid, error=str(exc)[:200])

    await websocket.accept()
    logger.info("websocket.connected", session_id=sid)

    redis_client = get_redis_client()
    event_bus = EventBus(redis_client) if redis_client else None
    tool_registry = ToolRegistry()
    llm = LLMClient()
    tool_executor = ToolExecutor(event_bus=event_bus)

    # Same persistent checkpointer as the SSE path — WS sessions must be
    # able to resume multi-turn state and conversational approval
    # checkpoints across reconnects.
    from nexus.config.settings import get_settings
    from nexus.db.base import async_session as _ws_session_factory
    from nexus.memory.checkpointer import get_checkpointer

    checkpointer = None
    _ws_settings = get_settings()
    if _ws_settings.memory.checkpointer_type == "postgres":
        try:
            checkpointer = await get_checkpointer()
        except Exception as exc:
            logger.warning("websocket.checkpointer_unavailable", error=str(exc))

    runner = AgentRunner(
        llm_client=llm,
        tool_executor=tool_executor,
        event_bus=event_bus,
        session_factory=_ws_session_factory,
        checkpointer=checkpointer,
    )

    connected = True
    heartbeat_task: asyncio.Task[None] | None = None
    run_task: asyncio.Task[None] | None = None
    conn_id = str(uuid.uuid4())

    async def _send(msg: dict[str, Any]) -> None:
        try:
            await websocket.send_json(msg)
        except Exception:
            pass

    async def _heartbeat() -> None:
        while connected:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_S)
            try:
                await websocket.send_json({"type": "heartbeat"})
            except Exception:
                break

    async def _run_agent(message: str) -> None:
        try:
            user_context = identity.to_dict() if identity is not None else None
            async for agent_event in runner.invoke(
                session_id=sid,
                user_message=message,
                user_context=user_context,
            ):
                if not connected:
                    return
                await _send(agent_event.to_dict())
        except Exception as exc:
            logger.error("websocket.run_error", session_id=sid, error=str(exc))
            if connected:
                await _send({"type": "error", "payload": {"message": str(exc)}})

    heartbeat_task = asyncio.ensure_future(_heartbeat())

    try:
        while connected:
            raw = await asyncio.wait_for(
                websocket.receive_text(),
                timeout=_HEARTBEAT_TIMEOUT_S * 3,
            )
            data: dict[str, Any] = json.loads(raw)
            msg_type: str = data.get("type", "message")

            if msg_type in ("message", "chat"):
                message: str = data.get("message") or data.get("payload", {}).get("text", "")
                if not message:
                    await _send({"type": "error", "payload": {"message": "Empty message"}})
                    continue
                run_task = asyncio.ensure_future(_run_agent(message))

            elif msg_type == "cancel":
                if run_task and not run_task.done():
                    run_task.cancel()
                await _send({"type": "cancelled"})

            elif msg_type == "ping":
                await _send({"type": "pong"})

    except asyncio.TimeoutError:
        pass
    except WebSocketDisconnect:
        pass
    except json.JSONDecodeError:
        logger.warning("websocket.invalid_json", session_id=sid)
    except Exception as exc:
        logger.error("websocket.error", session_id=sid, error=str(exc))
    finally:
        connected = False
        if run_task and not run_task.done():
            run_task.cancel()
        if heartbeat_task and not heartbeat_task.done():
            heartbeat_task.cancel()
        logger.info("websocket.disconnected", session_id=sid, duration_s=time.time())
