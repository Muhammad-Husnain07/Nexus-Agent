"""Redis pub/sub event bus for streaming agent and tool events.

Events are published as JSON envelopes on tenant/session-scoped channels so
that multiple frontend connections can subscribe and receive live updates.
An optional heartbeat keeps idle channels visible to subscribers.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

AGENT_EVENTS_CHANNEL = "agent_events:{session_id}"
TOOL_EVENTS_CHANNEL = "tool_events:{session_id}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def agent_channel(session_id: str | uuid.UUID) -> str:
    """Return the agent-events channel name for a session."""
    return AGENT_EVENTS_CHANNEL.format(session_id=session_id)


def tool_channel(session_id: str | uuid.UUID) -> str:
    """Return the tool-events channel name for a session."""
    return TOOL_EVENTS_CHANNEL.format(session_id=session_id)


class EventBus:
    """Publish and subscribe to JSON-serialized events over Redis pub/sub."""

    def __init__(self, redis_client: Redis[Any]) -> None:
        self._redis = redis_client

    async def publish(self, channel: str, event: dict[str, Any]) -> int:
        """Publish an event envelope to ``channel``.

        Args:
            channel: Channel name (use ``agent_channel`` / ``tool_channel``).
            event: Event payload dict. A ``type`` field is recommended.

        Returns:
            The number of clients that received the message.
        """
        envelope = {
            "type": event.get("type", "event"),
            "ts": _now_iso(),
            "payload": event,
        }
        return await self._redis.publish(channel, json.dumps(envelope))

    async def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]:
        """Yield parsed event envelopes published to ``channel``.

        The subscription is cleaned up automatically when the async iterator
        is closed (e.g. via ``async for`` break or generator shutdown).

        Args:
            channel: Channel name to subscribe to.

        Yields:
            Parsed event envelope dicts (``type``, ``ts``, ``payload``).
        """
        pubsub: PubSub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                yield json.loads(data)
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    async def heartbeat(self, channel: str, interval_s: int = 10) -> None:
        """Periodically publish a heartbeat event on ``channel``.

        Intended to be launched as a background task so subscribers can detect
        liveness even during idle periods.

        Args:
            channel: Channel to heartbeat on.
            interval_s: Seconds between heartbeats.
        """
        while True:
            await self.publish(channel, {"type": "heartbeat"})
            await asyncio.sleep(interval_s)
