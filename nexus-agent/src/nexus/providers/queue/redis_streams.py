"""Redis Streams task queue with consumer groups.

Uses Redis Streams (XADD/XREADGROUP/XACK) — supports consumer groups for
horizontal scaling, pending-entry lists for retries, and the existing Redis
deployment. Failures are negative-acked back to the stream so other workers
(or a retry pass) can pick them up.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import structlog

from nexus.redis_client.client import get_redis_client
from nexus.providers.queue.base import STREAM, TaskQueue

logger = structlog.get_logger("nexus.providers.queue.redis_streams")

_PENDING_MAX = 100  # scan bound for retryable pending entries


class RedisStreamsQueue(TaskQueue):
    """Redis Streams consumer-group queue."""

    def __init__(self) -> None:
        self._client = get_redis_client()

    async def enqueue(self, task_id: str, payload: dict[str, Any], group: str = "default") -> None:
        entry = {"task_id": task_id, "payload": json.dumps(payload, default=str)}
        try:
            await self._client.xadd(STREAM, entry)
        except Exception as exc:
            logger.warning("queue.enqueue_failed", task_id=task_id, error=str(exc)[:200])
            raise

    async def _ensure_group(self, group: str) -> None:
        """Create the consumer group if missing (idempotent)."""
        try:
            await self._client.xgroup_create(STREAM, group, id="0", mkstream=True)
        except Exception:
            pass  # group already exists

    async def claim(self, group: str = "default", consumer: str = "worker") -> dict[str, Any] | None:
        """Claim one task from the consumer group (non-blocking)."""
        await self._ensure_group(group)
        try:
            # 1. Retry pending entries first (previous failed claims)
            pending = await self._client.xpending_range(
                STREAM, group, min="-", max="+", count=_PENDING_MAX
            )
            if pending:
                entry_id = pending[0]["message_id"]
                claimed = await self._client.xclaim(
                    STREAM, group, consumer, min_idle_time=30_000, message_ids=[entry_id]
                )
                if claimed:
                    return self._decode(entry_id, claimed[0])

            # 2. New entries
            entries = await self._client.xreadgroup(
                group, consumer, {STREAM: ">"}, count=1, block=500
            )
            if not entries:
                return None
            for _, messages in entries:
                if messages:
                    entry_id, fields = messages[0]
                    return self._decode(entry_id, fields)
            return None
        except Exception as exc:
            logger.warning("queue.claim_failed", error=str(exc)[:200])
            return None

    async def ack(self, task_id: str, group: str = "default") -> None:
        try:
            await self._client.xack(STREAM, group, task_id)
        except Exception as exc:
            logger.warning("queue.ack_failed", task_id=task_id, error=str(exc)[:200])

    async def nack(self, task_id: str, group: str = "default") -> None:
        """Leave the entry in the pending list (idle-timeout re-claims it)."""
        # Nothing to do: xreadgroup already marks the entry pending; the
        # pending-scan in claim() will pick it up after min_idle_time.
        await self._client.xack(STREAM, group, task_id)
        # Re-add so it becomes pending again for retry
        task = await self._client.xrange(STREAM, min=task_id, max=task_id)
        if task:
            await self._client.xadd(STREAM, task[0][1])

    @staticmethod
    def _decode(entry_id: str, fields: dict[bytes | str, Any]) -> dict[str, Any] | None:
        def _s(v: Any) -> str:
            return v.decode() if isinstance(v, bytes) else str(v)

        task_id = _s(fields.get("task_id", ""))
        if not task_id:
            return None
        payload = {}
        try:
            payload = json.loads(_s(fields.get("payload", "{}")))
        except (json.JSONDecodeError, TypeError):
            payload = {}
        return {"task_id": task_id, "entry_id": entry_id, "payload": payload}
