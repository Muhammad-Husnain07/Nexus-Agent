"""Compiler Caches — ParseCache + PlanCache for skipping LLM on repeat queries.

Cache keys are SHA256 hashes of the input (query text + context fingerprint).
If a cache hit occurs, the SemanticParserNode and PlannerNode are entirely skipped,
saving ~13–30s per turn.

No hardcoded cache keys. All hashes are derived from runtime data.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog

logger = structlog.get_logger("nexus.compiler.cache")

# Default TTLs in seconds
_PARSE_CACHE_TTL: int = 3600  # 1 hour
_PLAN_CACHE_TTL: int = 300    # 5 minutes


def _make_key(*parts: str) -> str:
    """Create a SHA256 cache key from parts."""
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _query_fingerprint(query: str, available_tools: list[dict[str, Any]]) -> str:
    """Create a fingerprint of the query + available tools for cache keying.

    Includes tool names + versions so cache invalidates when tools change.
    """
    tool_info = sorted(
        f"{t.get('name','')}:{t.get('version',1)}" for t in available_tools if t.get("name")
    )
    return json.dumps({"q": query.strip().lower(), "tools": tool_info}, sort_keys=True)


# ============================================================================
# ParseCache — Cache IntentIR extraction results
# ============================================================================


class ParseCache:
    """Cache for IntentIR extraction results.

    Key: SHA256 of (query fingerprint + model name).
    Value: JSON-serialized list[IntentIR].

    Cache hit: SemanticParserNode returns cached IntentIR without LLM call.
    Cache miss: SemanticParserNode calls LLM, stores result in cache.

    TTL: 1 hour (configurable via settings).
    """

    def __init__(self, ttl: int = _PARSE_CACHE_TTL) -> None:
        self._ttl = ttl
        self._redis: Any = None
        self._memory: dict[str, tuple[float, str]] = {}  # key → (expiry, value)

    async def _get_redis(self) -> Any:
        if self._redis is None:
            try:
                from nexus.redis_client.client import get_redis_client
                self._redis = get_redis_client()
            except Exception:
                pass
        return self._redis

    def _build_key(self, query: str, tools: list[dict[str, Any]], model: str) -> str:
        return _make_key("parse", _query_fingerprint(query, tools), model)

    async def get(
        self,
        query: str,
        tools: list[dict[str, Any]],
        model: str,
    ) -> list[dict[str, Any]] | None:
        """Get cached IntentIR list for a query+tools+model combination.

        Returns:
            List of IntentIR dicts, or None if cache miss.
        """
        key = self._build_key(query, tools, model)

        # Try Redis first
        redis = await self._get_redis()
        if redis is not None:
            try:
                data = await redis.get(key)
                if data:
                    await redis.expire(key, self._ttl)
                    logger.debug("cache.parse_hit_redis", key=key[:12])
                    return json.loads(data)
            except Exception:
                pass

        # Fallback: in-memory
        entry = self._memory.get(key)
        if entry:
            expiry, value = entry
            if expiry > __import__("time").time():
                logger.debug("cache.parse_hit_memory", key=key[:12])
                return json.loads(value)

        logger.debug("cache.parse_miss", key=key[:12])
        return None

    async def set(
        self,
        query: str,
        tools: list[dict[str, Any]],
        model: str,
        intents: list[dict[str, Any]],
    ) -> None:
        """Cache IntentIR list for a query+tools+model combination."""
        key = self._build_key(query, tools, model)
        value = json.dumps(intents)
        expiry = __import__("time").time() + self._ttl

        # Redis
        redis = await self._get_redis()
        if redis is not None:
            try:
                await redis.setex(key, self._ttl, value)
                logger.debug("cache.parse_stored_redis", key=key[:12])
                return
            except Exception:
                pass

        # Fallback: in-memory
        self._memory[key] = (expiry, value)
        logger.debug("cache.parse_stored_memory", key=key[:12])

    async def invalidate(self, query: str, tools: list[dict[str, Any]], model: str) -> None:
        """Invalidate a cache entry (e.g., after registration change)."""
        key = self._build_key(query, tools, model)
        redis = await self._get_redis()
        if redis is not None:
            try:
                await redis.delete(key)
            except Exception:
                pass
        self._memory.pop(key, None)


# ============================================================================
# PlanCache — Cache compiled ExecutionIR DAGs
# ============================================================================


class PlanCache:
    """Cache for compiled execution plan DAGs.

    Key: SHA256 of (GoalIR fingerprints + available tools fingerprint).
    Value: JSON-serialized list[ExecutionIR].

    Cache hit: planner pipeline returns cached ExecutionIR without resolution.
    Cache miss: planner pipeline compiles, stores result in cache.

    TTL: 5 minutes (configurable via settings).
    """

    def __init__(self, ttl: int = _PLAN_CACHE_TTL) -> None:
        self._ttl = ttl
        self._redis: Any = None
        self._memory: dict[str, tuple[float, str]] = {}

    async def _get_redis(self) -> Any:
        if self._redis is None:
            try:
                from nexus.redis_client.client import get_redis_client
                self._redis = get_redis_client()
            except Exception:
                pass
        return self._redis

    def _build_key(
        self,
        goals: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> str:
        goal_fingerprint = json.dumps(
            sorted((g.get("action", ""), sorted(g.get("required_artifacts", []))) for g in goals)
        )
        tool_fingerprint = json.dumps(
            sorted(f"{t.get('name','')}:{t.get('version',1)}" for t in tools if t.get("name"))
        )
        return _make_key("plan", goal_fingerprint, tool_fingerprint)

    async def get(
        self,
        goals: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        key = self._build_key(goals, tools)
        redis = await self._get_redis()
        if redis is not None:
            try:
                data = await redis.get(key)
                if data:
                    await redis.expire(key, self._ttl)
                    return json.loads(data)
            except Exception:
                pass
        entry = self._memory.get(key)
        if entry:
            expiry, value = entry
            if expiry > __import__("time").time():
                return json.loads(value)
        return None

    async def set(
        self,
        goals: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        plan: list[dict[str, Any]],
    ) -> None:
        key = self._build_key(goals, tools)
        value = json.dumps(plan)
        expiry = __import__("time").time() + self._ttl
        redis = await self._get_redis()
        if redis is not None:
            try:
                await redis.setex(key, self._ttl, value)
                return
            except Exception:
                pass
        self._memory[key] = (expiry, value)


# ============================================================================
# Singleton instances
# ============================================================================

_parse_cache: ParseCache | None = None
_plan_cache: PlanCache | None = None


def get_parse_cache() -> ParseCache:
    global _parse_cache
    if _parse_cache is None:
        _parse_cache = ParseCache()
    return _parse_cache


def get_plan_cache() -> PlanCache:
    global _plan_cache
    if _plan_cache is None:
        _plan_cache = PlanCache()
    return _plan_cache
