"""Graceful degradation — handle LLM/tool/DB failures without crashing.

Provides a ``DegradationManager`` that checks circuit breaker states and
health endpoints, returning degraded responses when components are down.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.errors.base import ErrorCode
from nexus.redis_client.cache import RedisCache
from nexus.redis_client.client import get_redis_client

logger = structlog.get_logger("nexus.errors.graceful_degradation")

_DEGRADED_RESPONSE = (
    "I'm currently experiencing reduced functionality because one of my "
    "supporting services is temporarily unavailable.  Please try again in "
    "a few moments, or rephrase your request if it involves external tools."
)


class DegradationManager:
    """Monitors component health and provides degraded operation paths.

    Uses circuit breaker states to determine if a component is available.
    Falls back to cached responses or graceful messages.
    """

    def __init__(self) -> None:
        self._cache: RedisCache | None = None

    @property
    def cache(self) -> RedisCache | None:
        if self._cache is None:
            redis = get_redis_client()
            if redis is not None:
                self._cache = RedisCache(redis, prefix="nexus:degradation")
        return self._cache

    async def check_llm_available(self) -> bool:
        """Check if any LLM provider is available via circuit breaker states."""
        from nexus.errors.circuit_breaker import registry as cb_registry

        open_breakers = cb_registry.all_open()
        if not open_breakers:
            return True  # No open breakers = LLM available

        # If all registered LLM breakers are open, LLM is degraded
        llm_open = [n for n in open_breakers if _is_llm_breaker(n)]
        return len(llm_open) < 2  # Degrade only if most providers are open

    async def check_tool_available(self, tool_name: str) -> bool:
        """Check if a specific tool is available via circuit breaker state."""
        from nexus.errors.circuit_breaker import registry as cb_registry

        state = cb_registry.state_of(f"tool:{tool_name}")
        return state != "open"

    async def degraded_llm_response(self, query_hash: str | None = None) -> str:
        """Return a graceful degradation message for LLM failures.

        Args:
            query_hash: Optional hash of the user's query for cache lookup.

        Returns:
            A cached similar response, or a standard degraded message.
        """
        cache = self.cache
        if cache and query_hash:
            cached = await cache.get(f"llm_degraded:{query_hash}")
            if cached and isinstance(cached, str):
                return cached

        return _DEGRADED_RESPONSE

    async def degraded_tool_response(self, tool_name: str) -> dict[str, Any]:
        """Return a structured degraded response for a tool failure.

        Returns a dict that the agent can use to decide on alternative actions.
        """
        logger.warning("tool.degraded", tool_name=tool_name)
        return {
            "status": "degraded",
            "tool_name": tool_name,
            "error_code": ErrorCode.SERVICE_DEGRADED.value,
            "message": f"The tool '{tool_name}' is currently unavailable.  "
                       f"Please try again later or use an alternative tool.",
            "retryable": True,
        }

    async def check_db_available(self) -> bool:
        """Check database availability via a simple probe.

        Returns ``True`` if the DB appears to be available.
        """
        try:
            from nexus.db.base import async_session

            async with async_session() as session:
                from sqlalchemy import text

                await session.execute(text("SELECT 1"))
                return True
        except Exception:
            logger.warning("db.unavailable")
            return False


def _is_llm_breaker(breaker_name: str) -> bool:
    """Return True if the breaker name corresponds to an LLM provider."""
    return breaker_name.startswith("llm:") or not breaker_name.startswith("tool:")
