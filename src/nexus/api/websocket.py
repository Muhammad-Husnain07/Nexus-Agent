"""WebSocket endpoint for bidirectional agent communication.

Provides a WebSocket at ``/api/v1/sessions/{session_id}/ws`` where clients
can send messages and receive streaming agent events.  Supports multiple
subscribers per session via Redis pub/sub fan-out.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import suppress
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from nexus.agent.runner import AgentRunner
from nexus.llm.client import LLMClient
from nexus.redis_client.client import get_redis_client
from nexus.redis_client.pubsub import EventBus, agent_channel
from nexus.tools.discovery import DynamicToolSelector
from nexus.tools.executor import ToolExecutor
from nexus.tools.registry import ToolRegistry

logger = structlog.get_logger("nexus.api.websocket")

router = APIRouter(prefix="/sessions", tags=["chat"])


@router.websocket("/{session_id}/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:  # noqa: PLR0912, PLR0915
    """Bidirectional WebSocket for agent communication.

    The client sends JSON messages of the form:
    ``{"type": "message", "content": "user message"}``

    The server streams back agent events as JSON lines:
    ``{"type": "...", "payload": {...}, "ts": "..."}``

    Other subscribers listening on the same session receive events via
    Redis pub/sub fan-out.
    """
    await websocket.accept()
    session_id = websocket.path_params.get("session_id", str(uuid.uuid4()))
    sid = str(session_id)

    logger.info("websocket.connected", session_id=sid)

    redis_client = get_redis_client()
    event_bus = EventBus(redis_client) if redis_client else None
    tool_registry = ToolRegistry()
    llm = LLMClient()
    tool_executor = ToolExecutor(event_bus=event_bus)
    tool_selector = DynamicToolSelector(
        registry=tool_registry,
        llm_client=llm,
    )
    from nexus.db.base import async_session  # noqa: PLC0415

    runner = AgentRunner(
        llm_client=llm,
        tool_selector=tool_selector,
        tool_executor=tool_executor,
        event_bus=event_bus,
        session_factory=async_session,
    )

    pubsub = None
    pubsub_task: asyncio.Task[None] | None = None

    if redis_client:
        try:
            channel = agent_channel(sid)
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(channel)
        except Exception as exc:
            logger.warning("websocket.pubsub_failed", session_id=sid, error=str(exc))
            pubsub = None

    async def _broadcast(event_dict: dict[str, Any]) -> None:
        """Send an event to this WebSocket client."""
        try:
            await websocket.send_json(event_dict)
        except Exception as exc:
            logger.warning("websocket.send_failed", session_id=sid, error=str(exc))

    async def _listen_pubsub() -> None:
        """Read events from Redis pub/sub and broadcast to the WebSocket."""
        if pubsub is None:
            return
        try:
            async for message in pubsub.listen():
                if message is None:
                    continue
                msg_type = message.get("type", "")
                if msg_type != "message":
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                if isinstance(data, str):
                    try:
                        event_dict = json.loads(data)
                        await _broadcast(event_dict)
                    except json.JSONDecodeError:
                        pass
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("websocket.pubsub_listen_error", session_id=sid, error=str(exc))

    if pubsub is not None:
        pubsub_task = asyncio.create_task(_listen_pubsub())

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                await _broadcast({"type": "error", "payload": {"message": "Invalid JSON"}})
                continue

            msg_type = data.get("type", "message")
            content = data.get("content", "")

            if msg_type == "ping":
                await _broadcast({"type": "pong"})
                continue

            if msg_type == "cancel":
                logger.info("websocket.cancelled", session_id=sid)
                break

            if msg_type != "message" or not content:
                err_msg = "Unsupported type or empty content"
                await _broadcast({"type": "error", "payload": {"message": err_msg}})
                continue

            from nexus.db.context import get_tenant as _gt  # noqa: PLC0415

            ct = _gt()
            tid = str(ct) if ct else "00000000-0000-0000-0000-000000000001"
            default_user = "00000000-0000-0000-0000-000000000002"
            uid = default_user

            async for agent_event in runner.invoke(
                session_id=sid,
                user_message=content,
                tenant_id=tid,
                user_id=uid,
            ):
                await _broadcast(agent_event.to_dict())

            await _broadcast({"type": "done", "payload": {}})

    except WebSocketDisconnect:
        logger.info("websocket.disconnected", session_id=sid)
    except Exception as exc:
        logger.error("websocket.error", session_id=sid, error=str(exc))
        with suppress(Exception):
            await _broadcast({"type": "error", "payload": {"message": str(exc)}})
    finally:
        if pubsub_task is not None:
            pubsub_task.cancel()
            with suppress(asyncio.CancelledError):
                await pubsub_task
        if pubsub is not None:
            with suppress(Exception):
                await pubsub.unsubscribe()
                await pubsub.close()
        logger.info("websocket.closed", session_id=sid)
