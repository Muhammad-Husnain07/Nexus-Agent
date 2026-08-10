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


def _get_cache_ttl(cache_name: str) -> int:
    try:
        settings = get_settings()
        cache_config = getattr(settings, "cache", None)
        if cache_config is not None:
            return int(getattr(cache_config, f"{cache_name}_ttl", 0) or 0)
    except Exception:
        pass
    return 0


_CACHE_NS = "nexus:cache:"  # namespaced prefix so clear_all never touches other services' keys


def _make_key(*parts: str) -> str:
    raw = "|".join(parts)
    return f"{_CACHE_NS}{hashlib.sha256(raw.encode()).hexdigest()[:32]}"


def _registry_fingerprint() -> str:
    """Return a stable registry version fingerprint for cache keys.

    Prefers the deterministic structural ``registry_checksum`` (hashes nodes,
    templates, adjacency, providers — NOT timestamps), falling back to the
    compile timestamp. Any registry change (new tool, edited template,
    provider update) changes the fingerprint and invalidates cached plans.

    API-registered tools change the ``tool`` table without recompiling the
    graph — their updated_at + count is folded into the fingerprint so
    plans never go stale after tool registration/edits.
    """
    parts: list[str] = []
    try:
        from nexus.compiler.compiled_graph import get_compiled_graph
        g = get_compiled_graph()
        if g is not None:
            checksum = getattr(g, "registry_checksum", "") or ""
            if checksum:
                parts.append(f"reg:{checksum[:16]}")
            elif hasattr(g, "compiled_at"):
                parts.append(str(g.compiled_at))
    except Exception:
        pass

    # Tool-table mutation marker: API-registered tools don't recompile the
    # graph, so fold the registry's tool marker into the fingerprint — any
    # tool registration/edit/deregister invalidates cached plans.
    try:
        from nexus.tools.registry import get_tool_registry_marker

        marker = get_tool_registry_marker()
        if marker:
            parts.append(marker)
    except Exception:
        pass

    return "|".join(parts) if parts else ""


def _planner_prompt_fp() -> str:
    """P1-B.2: content fingerprint of the registered PLANNER prompt.

    Component-specific: only the logical_planner template participates in
    parse/plan cache keys — a response or router prompt change must not
    invalidate planned artifacts. Any failure → "prompt-unknown" (safe:
    cached entries simply stop matching old keys)."""
    try:
        from nexus.agent.prompts import prompt_manager

        return prompt_manager.fingerprint("logical_planner")
    except Exception:
        return "prompt-unknown"


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
        self._max_memory_entries: int = 1000
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
        # Bound the in-memory cache: opportunistically evict expired entries
        # on write so long-running servers don't grow unbounded.
        if len(self._memory) > self._max_memory_entries:
            now = time.time()
            expired = [k for k, (exp, _v) in self._memory.items() if exp <= now]
            for k in expired:
                self._memory.pop(k, None)
            if len(self._memory) > self._max_memory_entries:
                # Still over the cap — drop oldest (dict preserves insertion order)
                overflow = len(self._memory) - self._max_memory_entries
                for k in list(self._memory.keys())[:overflow]:
                    self._memory.pop(k, None)

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
                # Scoped delete by namespace prefix — NEVER flushdb (that
                # wipes every key on the shared Redis server).
                async for key in redis.scan_iter(match=f"{_CACHE_NS}*"):
                    await redis.delete(key)
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
        super().__init__(ttl or _get_cache_ttl("parse") or 3600)

    def _get_ttl(self) -> int:
        cfg_ttl = _get_cache_ttl("parse")
        return cfg_ttl if cfg_ttl > 0 else self._default_ttl

    def _build_key(self, query: str, tools: list[dict[str, Any]], model: str,
                   context: str = "") -> str:
        # Versioned key: the architecture cache fingerprint (over the whole
        # manifest — ADR 0008) plus the registry fingerprint — a cached plan
        # must never outlive the code that produced it (deployment-safe
        # invalidation). The fingerprint is the ONLY architecture version
        # in cache keys.
        # P1-B.2 COMPONENT-SPECIFIC PROMPT FP: the parse cache depends on
        # the PLANNER prompt (content hash) — a planner-prompt change
        # invalidates cached plans; a response/router prompt change does NOT.
        try:
            from nexus.agent.architecture import ArchitectureVersion

            _arch_fp = ArchitectureVersion.cache_fingerprint()
        except Exception:
            _arch_fp = "arch-unknown"
        return _make_key(
            "parse", _query_fingerprint(query, tools), model, context,
            _arch_fp,
            _planner_prompt_fp(),
        )

    async def get(
        self,
        query: str,
        tools: list[dict[str, Any]],
        model: str,
        context: str = "",
    ) -> list[dict[str, Any]] | None:
        key = self._build_key(query, tools, model, context)
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
        context: str = "",
    ) -> None:
        # Guard: don't cache empty workflows — they're likely planning failures
        if isinstance(intents, dict):
            nodes = intents.get("nodes", [])
            if not nodes:
                logger.debug("cache.parse_skip_empty", query=query[:50])
                return
        elif isinstance(intents, list) and not intents:
            logger.debug("cache.parse_skip_empty", query=query[:50])
            return

        key = self._build_key(query, tools, model, context)
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

    async def remove(
        self,
        query: str,
        tools: list[dict[str, Any]],
        model: str,
        context: str = "",
    ) -> None:
        """Remove the EXACT entry for (query, tools, model, context).

        SEMANTIC CACHE ELIGIBILITY (P2F): the validator/compiler remove a
        plan the moment its semantic verdict is REFINE/ABORT (or coverage
        < 100%, or an alignment violation, or a compile failure) — a
        syntactically valid plan is not semantically safe to cache. The
        key must match the writer's key exactly (context included), so the
        same entry the planner stored is the one removed.
        """
        key = self._build_key(query, tools, model, context)
        redis = await self._get_redis()
        if redis is not None:
            try:
                await redis.delete(key)
            except Exception:
                pass
        self._memory.pop(key, None)
        logger.info("cache.parse_removed", key=key[:12], query=query[:50])


# ============================================================================
# PlanCache
# ============================================================================


class PlanCache(_BaseCache):
    def __init__(self, ttl: int | None = None) -> None:
        super().__init__(ttl or _get_cache_ttl("plan") or 300)

    def _get_ttl(self) -> int:
        cfg_ttl = _get_cache_ttl("plan")
        return cfg_ttl if cfg_ttl > 0 else self._default_ttl

    def build_workflow_key(self, logical_workflow: dict[str, Any]) -> str:
        """Versioned cache key for a COMPILED execution graph.

        Keyed by the canonical logical-workflow content + registry
        fingerprint + compiler + artifact-schema versions — the compiled
        graph for an identical plan is reused across turns without
        re-running codegen/resolution, and can never outlive the code or
        registry that produced it.
        """
        nodes = logical_workflow.get("nodes") if isinstance(logical_workflow, dict) else []
        wf_fp = json.dumps(
            [
                {
                    "op": str(n.get("op") or ""),
                    "inputs": {k: str(v) for k, v in (n.get("inputs") or {}).items()},
                    "depends_on": [str(d) for d in (n.get("depends_on") or [])],
                    "iterate_over": str(n.get("iterate_over") or ""),
                    "ref": str(n.get("ref") or ""),
                    "condition": str(n.get("condition") or ""),
                    "branch_true": str(n.get("branch_true") or ""),
                    "branch_false": str(n.get("branch_false") or ""),
                }
                for n in nodes
                if isinstance(n, dict)
            ],
            sort_keys=True,
        )
        # Collections shape participates in the key: two workflows with
        # identical ops but different iterate_over collections compile to
        # different maps — they must never share a cached graph.
        _collections = (
            logical_workflow.get("collections")
            if isinstance(logical_workflow, dict)
            else None
        )
        if _collections:
            wf_fp += "|cols:" + json.dumps(_collections, sort_keys=True)[:4000]
        try:
            from nexus.agent.architecture import ArchitectureVersion

            _arch_fp = ArchitectureVersion.cache_fingerprint()
        except Exception:
            _arch_fp = "arch-unknown"
        reg_fp = _registry_fingerprint() or ""
        return _make_key(
            "plan", wf_fp, _arch_fp, reg_fp,
            # P1-B.2: the plan cache depends on the PLANNER prompt content —
            # planner-prompt changes invalidate compiled graphs; response
            # prompt changes do not.
            _planner_prompt_fp(),
        )

    async def get_workflow(self, logical_workflow: dict[str, Any]) -> dict[str, Any] | None:
        """Retrieve a cached compiled ExecutionGraph dict (or None)."""
        key = self.build_workflow_key(logical_workflow)
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

    async def set_workflow(self, logical_workflow: dict[str, Any], graph: dict[str, Any]) -> None:
        """Store a compiled ExecutionGraph dict under its versioned key."""
        key = self.build_workflow_key(logical_workflow)
        value = json.dumps(graph)
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
