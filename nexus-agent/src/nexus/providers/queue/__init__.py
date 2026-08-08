"""Queue provider factory — pluggable task queue selection."""

from __future__ import annotations

from nexus.config.settings import get_settings
from nexus.providers.queue.base import STREAM, TaskQueue  # noqa: F401

_queue: TaskQueue | None = None


def get_queue() -> TaskQueue:
    """Return the configured task queue (cached singleton)."""
    global _queue  # noqa: PLW0603
    if _queue is not None:
        return _queue
    settings = get_settings()
    transport = getattr(settings, "queue", None)
    provider = getattr(transport, "provider", "redis_streams") if transport else "redis_streams"
    if provider == "redis_streams":
        from nexus.providers.queue.redis_streams import RedisStreamsQueue

        _queue = RedisStreamsQueue()
    else:
        raise ValueError(f"Unsupported queue provider: {provider}")
    return _queue
