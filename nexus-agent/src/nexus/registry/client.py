"""RegistryClient — cached reader for CapabilityModel metadata.

Reads ``intent_profiles``, ``input_policy``, and ``output_contract``
from the DB registry and caches them with a configurable TTL.

No hardcoded capability names or parameter mappings — all data is
read dynamically from the database.
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from nexus.db.models.registry import CapabilityModel

logger = structlog.get_logger("nexus.registry.client")

_CACHE_TTL_S: int = 300  # 5 minutes


class RegistryClient:
    """Cached reader for CapabilityModel intent profiles, input policies, and output contracts.

    Usage::

        client = RegistryClient(db_session)
        capability = await client.get_capability("get_weather")
        profiles = capability.intent_profiles  # {"current": {"current_weather": True}}
        policy = capability.input_policy          # {"defaults": {"timezone": "auto"}}
        contract = capability.output_contract     # {"required_any_of": ["$.current_weather"]}
    """

    def __init__(self, db_session: AsyncSession) -> None:
        self._db = db_session
        self._cache: dict[str, tuple[float, CapabilityModel | None]] = {}

    async def get_capability(self, logical_op_name: str) -> CapabilityModel | None:
        """Fetch a capability by ``logical_op_name`` with cache.

        Caches for ``_CACHE_TTL_S`` seconds to avoid repeated DB queries
        during pass iterations.
        """
        now = time.monotonic()
        cached = self._cache.get(logical_op_name)
        if cached is not None and (now - cached[0]) < _CACHE_TTL_S:
            return cached[1]

        result = await self._db.execute(
            select(CapabilityModel).where(
                CapabilityModel.logical_op_name == logical_op_name,
                CapabilityModel.enabled == True,
            )
        )
        capability = result.scalar_one_or_none()
        self._cache[logical_op_name] = (now, capability)
        return capability

    async def get_all_capabilities(self) -> list[CapabilityModel]:
        """Fetch all enabled capabilities from the DB (uncached)."""
        result = await self._db.execute(
            select(CapabilityModel).where(CapabilityModel.enabled == True)
        )
        return list(result.scalars().all())

    async def get_intent_profiles(self, logical_op_name: str) -> dict[str, Any]:
        """Get intent profiles for a capability (or empty dict)."""
        cap = await self.get_capability(logical_op_name)
        return (cap.intent_profiles or {}) if cap else {}

    async def get_input_policy(self, logical_op_name: str) -> dict[str, Any]:
        """Get input policy (defaults + computed) for a capability."""
        cap = await self.get_capability(logical_op_name)
        return (cap.input_policy or {}) if cap else {}

    async def get_output_contract(self, logical_op_name: str) -> dict[str, Any]:
        """Get output contract for a capability."""
        cap = await self.get_capability(logical_op_name)
        return (cap.output_contract or {}) if cap else {}

    def clear_cache(self) -> None:
        """Reset the cache (e.g., after a registry update)."""
        self._cache.clear()
