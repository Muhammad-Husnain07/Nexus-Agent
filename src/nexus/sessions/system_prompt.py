"""Dynamic system prompt assembly per session — identity, tools, tenant, user."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.context import get_tenant
from nexus.db.models.memory import Memory as MemoryModel
from nexus.db.models.tenant import Tenant as TenantModel
from nexus.db.repositories import TenantScopedRepository
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.sessions.system_prompt")

_PLATFORM_IDENTITY = (
    "You are Nexus Agent, a vendor-neutral AI orchestration assistant. "
    "You help users achieve their goals by planning, reasoning, "
    "and invoking tools on their behalf."
)

_OUTPUT_GUIDELINES = (
    "- If the user's request is ambiguous or missing required information, "
    "ask clarifying questions before acting.\n"
    "- If a tool requires user approval (high-risk), present the "
    "tool call details and wait for confirmation before executing.\n"
    "- Provide clear, concise explanations of your actions and results.\n"
    "- If you cannot complete a request safely or ethically, explain why."
)


class SystemPromptBuilder:
    """Assembles the system prompt dynamically per session.

    The prompt includes:
      1. Platform identity and capabilities
      2. Available tool categories (names only)
      3. Tenant-specific instructions (from Tenant.settings)
      4. User preferences (from Memory:preference)
      5. Current date/time and timezone
      6. Output guidelines

    Results are cached per ``(tenant_id, user_id, session_id)`` tuple
    and busted when preferences or tenant settings change.
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._llm = llm_client
        self._cache: dict[str, str] = {}

    def _cache_key(self, tenant_id: uuid.UUID | None, user_id: uuid.UUID | None) -> str:
        raw = f"{tenant_id}:{user_id}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def build(
        self,
        session: Any,
        tenant: TenantModel | None = None,
        tool_categories: list[str] | None = None,
        session_db: AsyncSession | None = None,
    ) -> str:
        """Build the full system prompt for a session.

        Args:
            session: Session model or object with tenant_id, user_id, id.
            tenant: Pre-loaded Tenant model (fetched if None).
            tool_categories: List of available tool category names.
            session_db: DB session for loading tenant + preferences.

        Returns:
            The assembled system prompt string.
        """
        tenant_id = getattr(session, "tenant_id", None) or get_tenant()
        user_id = getattr(session, "user_id", None)
        sid = getattr(session, "id", None)

        ck = self._cache_key(tenant_id, user_id)
        cached = self._cache.get(ck)
        if cached is not None:
            return cached

        parts: list[str] = []

        # 1. Platform identity
        parts.append(_PLATFORM_IDENTITY)

        # 2. Tool categories
        if tool_categories:
            cats = ", ".join(sorted(tool_categories))
            parts.append(f"Available tool categories: {cats}")

        # 3. Tenant instructions
        if tenant is None and session_db is not None and tenant_id is not None:
            repo = TenantScopedRepository(session_db, TenantModel)
            tenant = await repo.get(tenant_id)  # type: ignore[arg-type]

        if tenant and tenant.settings:
            instructions = tenant.settings.get("instructions")
            if instructions:
                parts.append(f"Tenant instructions: {instructions}")

        # 4. User preferences
        if session_db is not None and tenant_id is not None:
            preferences = await self._load_preferences(session_db, tenant_id, user_id)
            if preferences:
                parts.append(f"User preferences: {preferences}")

        # 5. Current date/time
        now = datetime.now(UTC)
        date_str = now.strftime("%A, %B %d, %Y at %H:%M UTC")
        parts.append(f"Current date and time: {date_str}")

        # 6. Output guidelines
        parts.append(_OUTPUT_GUIDELINES)

        result = "\n\n".join(parts)

        self._cache[ck] = result
        return result

    async def _load_preferences(
        self,
        session_db: AsyncSession,
        tenant_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
    ) -> str | None:
        """Load user preference memory entries and format as text."""
        if user_id is None:
            return None

        repo = TenantScopedRepository(session_db, MemoryModel)
        memories = await repo.find(
            kind="preference",
            tenant_id=tenant_id,
        )
        # Filter by user_id — Memory doesn't have a direct user FK,
        # so match via content metadata if available
        relevant = []
        for mem in memories:
            meta = mem.metadata_ or {}
            if meta.get("user_id") == str(user_id):
                relevant.append(mem.content)

        if not relevant:
            return None

        return "; ".join(relevant)

    def invalidate_cache(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Bust the cached prompt for a tenant+user pair."""
        ck = self._cache_key(tenant_id, user_id)
        self._cache.pop(ck, None)
