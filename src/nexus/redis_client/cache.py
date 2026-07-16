"""Redis-backed async cache for short-term data (LLM responses, tool metadata)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from redis.asyncio import Redis


class RedisCache:
    """TTL-based JSON cache backed by Redis.

    All keys are namespaced via ``prefix`` to avoid collisions with other
    Redis consumers (locks, rate limits, pub/sub).
    """

    def __init__(self, redis_client: Redis[Any], prefix: str = "nexus:cache") -> None:
        self._redis = redis_client
        self._prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    async def get(self, key: str) -> Any | None:
        """Return the decoded JSON value for ``key`` or ``None`` if absent."""
        raw = await self._redis.get(self._key(key))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    async def set(self, key: str, value: Any, ttl_s: int = 300) -> None:
        """Store ``value`` as JSON under ``key`` with a TTL in seconds."""
        await self._redis.set(self._key(key), json.dumps(value), ex=ttl_s)

    async def delete(self, key: str) -> int:
        """Delete ``key``; returns number of keys removed (0 or 1)."""
        return await self._redis.delete(self._key(key))

    async def exists(self, key: str) -> bool:
        """Return True if ``key`` exists in the cache."""
        return bool(await self._redis.exists(self._key(key)))

    async def clear_pattern(self, pattern: str) -> int:
        """Delete all keys matching ``pattern`` (within this cache prefix).

        The pattern is relative to the configured ``prefix`` (e.g. ``foo:*``
        matches ``<prefix>:foo:1``). Keys are collected before deletion to
        avoid mutating the iterator while it is in use.
        """
        full = self._key(pattern)
        keys = [k async for k in self._redis.scan_iter(match=full)]
        for k in keys:
            await self._redis.delete(k)
        return len(keys)

    async def get_llm_response(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> str | None:
        """Retrieve a cached LLM response.

        Args:
            model: Model identifier used for the request.
            messages: The exact message list (serialized into the key).
            tools: Optional tool definitions (serialized into the key).

        Returns:
            The cached response string, or ``None`` if not present.
        """
        key = self._llm_key(model, messages, tools)
        return await self.get(key)

    async def set_llm_response(
        self,
        model: str,
        messages: list[dict[str, Any]],
        response: str,
        tools: list[dict[str, Any]] | None = None,
        ttl_s: int = 3600,
    ) -> None:
        """Cache an LLM response keyed by (model, messages, tools)."""
        key = self._llm_key(model, messages, tools)
        await self.set(key, response, ttl_s=ttl_s)

    @staticmethod
    def _llm_key(
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> str:
        payload = json.dumps(
            {"model": model, "messages": messages, "tools": tools or []},
            sort_keys=True,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"llm:{digest}"
