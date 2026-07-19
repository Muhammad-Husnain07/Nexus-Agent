"""WebSocket endpoint for bidirectional agent communication."""
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


@router.websocket("/{session_id}/ws")
async def handle_websocket(websocket: WebSocket) -> None:
    """Accept a WebSocket connection, run the agent, and stream events.

    The client sends JSON messages and receives a stream of ``AgentEvent``
    dicts.
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

    runner = AgentRunner(
        llm_client=llm,
        tool_selector=tool_selector,
        tool_executor=tool_executor,
        event_bus=event_bus,
        session_factory=None,
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
            async for agent_event in runner.invoke(
                session_id=sid,
                user_message=message,
                tenant_id="00000000-0000-0000-0000-000000000001",
                user_id="00000000-0000-0000-0000-000000000002",
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
