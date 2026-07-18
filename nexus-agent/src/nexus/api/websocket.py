"""WebSocket endpoint for bidirectional agent communication.

Provides a WebSocket at ``/api/v1/sessions/{session_id}/ws`` where clients
can send messages and receive streaming agent events.  Supports multiple
subscribers per session via Redis pub/sub fan-out.

Embedded widget clients can connect with ``?token=`` for token-based auth.
"""

from __future__ import annotations

import asyncio
import json
import time
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

_HEARTBEAT_INTERVAL_S: float = 30.0
_HEARTBEAT_TIMEOUT_S: float = 10.0


async def _validate_embed_token(websocket: WebSocket) -> tuple[str | None, str | None]:
    """Validate an embed token from WebSocket query params.

    Returns ``(embed_id, token)`` if valid, ``(None, None)`` otherwise.
    """
    token = websocket.query_params.get("token")
    if not token:
        return None, None

    from sqlalchemy import select  # noqa: PLC0415

    from nexus.db.base import async_session as _session_factory  # noqa: PLC0415
    from nexus.db.models.embed import EmbedConfig  # noqa: PLC0415

    try:
        async with _session_factory() as session:
            result = await session.execute(
                select(EmbedConfig).where(
                    EmbedConfig.token == token,
                    EmbedConfig.is_revoked == False,  # noqa: E712
                )
            )
            config = result.scalar_one_or_none()
            if config is None:
                return None, None
            return str(config.id), token
    except Exception as exc:
        logger.warning("embed.ws_token_validation_failed", error=str(exc))
        return None, None


async def _track_embed_session(token: str, action: str, duration_s: float = 0.0) -> None:
    """Track embed session lifecycle in Redis analytics counters."""
    redis = get_redis_client()
    if redis is None:
        return
    try:
        if action == "start":
            await redis.incr(f"embed:active_sessions:{token}")
            await redis.zadd(f"embed:sessions:{token}", {str(time.time()): time.time()})
            await redis.expire(f"embed:active_sessions:{token}", 86400)
        elif action == "end":
            await redis.decr(f"embed:active_sessions:{token}")
            if duration_s > 0:
                await redis.zadd(
                    f"embed:session_durations:{token}", {duration_s: time.time()}
                )
        elif action == "message":
            await redis.incr(f"embed:messages:{token}")
    except Exception as exc:
        logger.debug("embed.analytics_error", action=action, error=str(exc))


@router.websocket("/{session_id}/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:  # noqa: PLR0912, PLR0915
    """Bidirectional WebSocket for agent communication.

    Accepts an optional ``?token=`` query param for embed widget auth.
    The client sends JSON messages of the form:
    ``{"type": "message", "content": "user message"}``

    Embed clients can send:
    - ``{"type": "embed_event", "event": "resize", "payload": {...}}``
    - ``{"type": "embed_event", "event": "theme_change", "payload": {...}}``
    - ``{"type": "pong"}`` (heartbeat response)

    The server streams back agent events as JSON lines:
    ``{"type": "...", "payload": {...}, "ts": "..."}``
    """
    await websocket.accept()
    session_id = websocket.path_params.get("session_id", str(uuid.uuid4()))
    sid = str(session_id)

    # ── Embed token authentication ──────────────────────────────────────────
    embed_id, embed_token = await _validate_embed_token(websocket)
    is_embed = embed_id is not None and embed_token is not None

    if is_embed:
        await _track_embed_session(embed_token, "start")
        logger.info(
            "embed.websocket.connected",
            session_id=sid,
            embed_id=embed_id,
            token_prefix=embed_token[:12],
        )
    else:
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

    # ── Heartbeat tracking ──────────────────────────────────────────────────
    last_pong: float = time.time()
    heartbeat_stop = asyncio.Event()

    async def _heartbeat() -> None:
        """Periodically ping the client and disconnect if no pong received."""
        nonlocal last_pong
        try:
            while not heartbeat_stop.is_set():
                await asyncio.sleep(_HEARTBEAT_INTERVAL_S)
                if heartbeat_stop.is_set():
                    break
                if time.time() - last_pong > _HEARTBEAT_INTERVAL_S + _HEARTBEAT_TIMEOUT_S:
                    logger.warning("websocket.heartbeat_timeout", session_id=sid)
                    break
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    heartbeat_task = asyncio.create_task(_heartbeat())

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

    session_start = time.time()

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

            # ── Heartbeat ───────────────────────────────────────────────────
            if msg_type == "pong":
                last_pong = time.time()
                continue

            # ── Cancel ─────────────────────────────────────────────────────
            if msg_type == "cancel":
                logger.info("websocket.cancelled", session_id=sid)
                break

            # ── Embed events ────────────────────────────────────────────────
            if msg_type == "embed_event":
                await _handle_embed_event(
                    websocket, data, sid, embed_token, _broadcast
                )
                continue

            # ── Regular message ─────────────────────────────────────────────
            if msg_type != "message" or not content:
                err_msg = "Unsupported type or empty content"
                await _broadcast({"type": "error", "payload": {"message": err_msg}})
                continue

            from nexus.db.context import get_tenant as _gt  # noqa: PLC0415

            ct = _gt()
            tid = str(ct) if ct else "00000000-0000-0000-0000-000000000001"
            default_user = "00000000-0000-0000-0000-000000000002"
            uid = default_user

            if is_embed:
                await _track_embed_session(embed_token, "message")

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
        heartbeat_stop.set()
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task

        if is_embed and embed_token:
            duration_s = time.time() - session_start
            await _track_embed_session(embed_token, "end", duration_s=duration_s)

        if pubsub_task is not None:
            pubsub_task.cancel()
            with suppress(asyncio.CancelledError):
                await pubsub_task
        if pubsub is not None:
            with suppress(Exception):
                await pubsub.unsubscribe()
                await pubsub.close()
        logger.info("websocket.closed", session_id=sid)


async def _handle_embed_event(
    websocket: WebSocket,
    data: dict[str, Any],
    sid: str,
    embed_token: str | None,
    broadcast: Any,
) -> None:
    """Handle embed-specific WebSocket events."""
    event = data.get("event", "")
    payload = data.get("payload", {})

    if event == "resize":
        logger.info(
            "embed.resize",
            session_id=sid,
            width=payload.get("width"),
            height=payload.get("height"),
        )
        await broadcast({"type": "embed_event", "event": "resize_ack", "payload": {}})

    elif event == "theme_change":
        logger.info("embed.theme_change", session_id=sid, theme=payload.get("theme"))
        await broadcast({"type": "embed_event", "event": "theme_change_ack", "payload": {}})

    elif event == "analytics":
        redis = get_redis_client()
        if redis and embed_token:
            try:
                msg_count = await redis.get(f"embed:messages:{embed_token}") or 0
                active = await redis.get(f"embed:active_sessions:{embed_token}") or 0
                await broadcast({
                    "type": "embed_event",
                    "event": "analytics",
                    "payload": {
                        "message_count": int(msg_count),
                        "active_sessions": int(active),
                    },
                })
            except Exception as exc:
                logger.debug("embed.analytics_fetch_error", error=str(exc))

    else:
        await broadcast({
            "type": "embed_event",
            "event": "error",
            "payload": {"message": f"Unknown embed event: {event}"},
        })
