"""Compiler Caches — ParseCache + PlanCache for skipping LLM on repeat queries.

Cache keys are SHA256 hashes of the input (query text + context fingerprint).
If a cache hit occurs, the SemanticParserNode and PlannerNode are entirely skipped,
saving ~13–30s per turn.

No hardcoded cache keys. All hashes are derived from runtime data.
Cache TTLs are read from settings (falling back to defaults).
Registry version is included in fingerprints to invalidate on registry changes.
``invalidate_all_caches()`` is called after registry re-compilation.
``stats()`` provides hit/miss rates for observability.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import structlog

from nexus.config.settings import get_settings

logger = structlog.get_logger("nexus.compiler.cache")

_DEFAULT_PARSE_CACHE_TTL: int = 3600
_DEFAULT_PLAN_CACHE_TTL: int = 300


def _get_cache_ttl(cache_name: str) -> int:
    try:
        settings = get_settings()
        cache_config = getattr(settings, "cache", None)
        if cache_config is not None:
            return int(getattr(cache_config, f"{cache_name}_ttl", 0) or 0)
    except Exception:
        pass
    return 0


def _make_key(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _registry_fingerprint() -> str:
    try:
        from nexus.compiler.compiled_graph import get_compiled_graph
        g = get_compiled_graph()
        if g is not None and hasattr(g, "compiled_at"):
            return str(g.compiled_at)
    except Exception:
        pass
    return ""


def _query_fingerprint(query: str, available_tools: list[dict[str, Any]]) -> str:
    tool_info = sorted(
        f"{t.get('name','')}:{t.get('version',1)}" for t in available_tools if t.get("name")
    )
    reg_fp = _registry_fingerprint()
    data: dict[str, Any] = {"q": query.strip().lower(), "tools": tool_info}
    if reg_fp:
        data["reg"] = reg_fp
    return json.dumps(data, sort_keys=True)


# ============================================================================
# BaseCache — shared hit/miss tracking + dual-backend
# ============================================================================


class _BaseCache:
    def __init__(self, default_ttl: int) -> None:
        self._default_ttl = default_ttl
        self._redis: Any = None
        self._memory: dict[str, tuple[float, str]] = {}
        self._hits: int = 0
        self._misses: int = 0

    async def _get_redis(self) -> Any:
        if self._redis is None:
            try:
                from nexus.redis_client.client import get_redis_client
                self._redis = get_redis_client()
            except Exception:
                pass
        return self._redis

    def _record_hit(self) -> None:
        self._hits += 1

    def _record_miss(self) -> None:
        self._misses += 1

    async def _get_from_redis(self, key: str) -> str | None:
        redis = await self._get_redis()
        if redis is None:
            return None
        try:
            data = await redis.get(key)
            if data:
                await redis.expire(key, self._get_ttl())
                return data
        except Exception:
            pass
        return None

    def _get_from_memory(self, key: str) -> str | None:
        entry = self._memory.get(key)
        if entry:
            expiry, value = entry
            if expiry > time.time():
                return value
        return None

    def _store_in_memory(self, key: str, value: str) -> None:
        expiry = time.time() + self._get_ttl()
        self._memory[key] = (expiry, value)

    async def _store_in_redis(self, key: str, value: str) -> bool:
        redis = await self._get_redis()
        if redis is None:
            return False
        try:
            await redis.setex(key, self._get_ttl(), value)
            return True
        except Exception:
            return False

    def _get_ttl(self) -> int:
        return self._default_ttl

    async def clear_all(self) -> None:
        self._memory.clear()
        redis = await self._get_redis()
        if redis is not None:
            try:
                await redis.flushdb()
            except Exception:
                pass

    def stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total": total,
            "hit_rate": round(self._hits / total, 4) if total > 0 else 0.0,
            "memory_entries": len(self._memory),
        }


# ============================================================================
# ParseCache
# ============================================================================


class ParseCache(_BaseCache):
    def __init__(self, ttl: int | None = None) -> None:
        super().__init__(ttl or _DEFAULT_PARSE_CACHE_TTL)

    def _get_ttl(self) -> int:
        cfg_ttl = _get_cache_ttl("parse")
        return cfg_ttl if cfg_ttl > 0 else self._default_ttl

    def _build_key(self, query: str, tools: list[dict[str, Any]], model: str) -> str:
        return _make_key("parse", _query_fingerprint(query, tools), model)

    async def get(
        self,
        query: str,
        tools: list[dict[str, Any]],
        model: str,
    ) -> list[dict[str, Any]] | None:
        key = self._build_key(query, tools, model)
        raw = await self._get_from_redis(key)
        if raw is not None:
            self._record_hit()
            logger.debug("cache.parse_hit_redis", key=key[:12])
            return json.loads(raw)
        raw = self._get_from_memory(key)
        if raw is not None:
            self._record_hit()
            logger.debug("cache.parse_hit_memory", key=key[:12])
            return json.loads(raw)
        self._record_miss()
        logger.debug("cache.parse_miss", key=key[:12])
        return None

    async def set(
        self,
        query: str,
        tools: list[dict[str, Any]],
        model: str,
        intents: list[dict[str, Any]],
    ) -> None:
        key = self._build_key(query, tools, model)
        value = json.dumps(intents)
        if await self._store_in_redis(key, value):
            logger.debug("cache.parse_stored_redis", key=key[:12])
            return
        self._store_in_memory(key, value)
        logger.debug("cache.parse_stored_memory", key=key[:12])

    async def invalidate(self, query: str, tools: list[dict[str, Any]], model: str) -> None:
        key = self._build_key(query, tools, model)
        redis = await self._get_redis()
        if redis is not None:
            try:
                await redis.delete(key)
            except Exception:
                pass
        self._memory.pop(key, None)


# ============================================================================
# PlanCache
# ============================================================================


class PlanCache(_BaseCache):
    def __init__(self, ttl: int | None = None) -> None:
        super().__init__(ttl or _DEFAULT_PLAN_CACHE_TTL)

    def _get_ttl(self) -> int:
        cfg_ttl = _get_cache_ttl("plan")
        return cfg_ttl if cfg_ttl > 0 else self._default_ttl

    def _build_key(self, goals: list[dict[str, Any]], tools: list[dict[str, Any]]) -> str:
        goal_fingerprint = json.dumps(
            sorted((g.get("action", ""), sorted(g.get("required_artifacts", []))) for g in goals)
        )
        tool_fingerprint = json.dumps(
            sorted(f"{t.get('name','')}:{t.get('version',1)}" for t in tools if t.get("name"))
        )
        reg_fp = _registry_fingerprint()
        parts = ["plan", goal_fingerprint, tool_fingerprint]
        if reg_fp:
            parts.append(reg_fp)
        return _make_key(*parts)

    async def get(
        self,
        goals: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        key = self._build_key(goals, tools)
        raw = await self._get_from_redis(key)
        if raw is not None:
            self._record_hit()
            return json.loads(raw)
        raw = self._get_from_memory(key)
        if raw is not None:
            self._record_hit()
            return json.loads(raw)
        self._record_miss()
        return None

    async def set(
        self,
        goals: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        plan: list[dict[str, Any]],
    ) -> None:
        key = self._build_key(goals, tools)
        value = json.dumps(plan)
        if await self._store_in_redis(key, value):
            return
        self._store_in_memory(key, value)


# ============================================================================
# Singleton accessors
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


async def invalidate_all_caches() -> None:
    """Clear all cache entries on registry re-compilation."""
    global _parse_cache, _plan_cache
    if _parse_cache is not None:
        await _parse_cache.clear_all()
    if _plan_cache is not None:
        await _plan_cache.clear_all()
    _parse_cache = None
    _plan_cache = None
    logger.info("cache.all_invalidated")
