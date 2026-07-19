"""DynamicToolSelector — discovers relevant tools for a user message."""

from __future__ import annotations

import hashlib
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.config.settings import get_settings
from nexus.llm.client import LLMClient
from nexus.redis_client.cache import RedisCache
from nexus.tools.registry import ToolRegistry
from nexus.tools.schemas import ToolRead

logger = structlog.get_logger("nexus.tools.discovery")

DISCOVERY_CACHE_TTL_S: int = 300
MAX_TOOLS_FOR_LLM_RERANK: int = 5


class DynamicToolSelector:
    """Selects the most relevant tools for a given user message.

    Uses semantic search (embedding-based) to find candidate tools, then
    optionally asks the LLM to re-rank them. Results are cached in Redis.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        llm_client: LLMClient | None = None,
        cache: RedisCache | None = None,
    ) -> None:
        self._registry = registry
        self._llm = llm_client or LLMClient()
        self._cache = cache

    async def select(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        message: str,
        context: str = "",
        k: int = 10,
    ) -> list[ToolRead]:
        """Return the top-k most relevant tools for the given message + context."""
        cache_key = self._cache_key(tenant_id, message, context)

        cached = await self._check_cache(cache_key)
        if cached is not None:
            return cached

        query_text = f"{message}\n{context}" if context else message
        results = await self._registry.search_semantic(session, tenant_id, query_text, k=k)

        tools = [r.tool for r in results]
        if len(tools) > MAX_TOOLS_FOR_LLM_RERANK:
            tools = await self._llm_rerank(message, tools)

        await self._set_cache(cache_key, tools)
        return tools

    async def _llm_rerank(
        self,
        message: str,
        tools: list[ToolRead],
    ) -> list[ToolRead]:
        prompt = (
            f"Given this user request:\n{message}\n\n"
            f"Rank these tools by relevance. Return only the tool names in order, "
            f"comma-separated, from most to least relevant:\n"
            + "\n".join(f"- {t.name}: {t.description}" for t in tools)
        )
        try:
            response = await self._llm.complete(
                model=get_settings().llm.default_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=256,
                temperature=0,
            )
            content = response.content or ""
            ranked_names = [n.strip() for n in content.split(",") if n.strip()]
            name_map = {t.name: t for t in tools}
            ranked = [name_map[n] for n in ranked_names if n in name_map]
            remaining = [t for t in tools if t.name not in ranked_names]
            return ranked + remaining
        except Exception:
            logger.warning("llm_rerank.failed", exc_info=True)
            return tools

    def _cache_key(self, tenant_id: uuid.UUID, message: str, context: str) -> str:
        raw = f"{tenant_id}|{message}|{context}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return f"tools:discovery:{tenant_id}:{digest}"

    async def _check_cache(self, key: str) -> list[ToolRead] | None:
        if self._cache is None:
            return None
        raw = await self._cache.get(key)
        if raw is None:
            return None
        try:
            return [ToolRead(**item) for item in raw]
        except Exception:
            await self._cache.delete(key)
            return None

    async def _set_cache(self, key: str, tools: list[ToolRead]) -> None:
        if self._cache is None:
            return
        raw = [t.model_dump(mode="json") for t in tools]
        await self._cache.set(key, raw, ttl_s=DISCOVERY_CACHE_TTL_S)
