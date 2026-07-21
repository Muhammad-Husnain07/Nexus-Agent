"""Dynamic system prompt assembly per session — identity, tools, user."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models.memory import Memory as MemoryModel
from nexus.db.repositories import GenericRepository
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
    """Assembles the system prompt dynamically per session."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._llm = llm_client
        self._cache: dict[str, str] = {}

    async def build(
        self,
        session: Any,
        user: object | None = None,
        tool_categories: list[str] | None = None,
        session_db: AsyncSession | None = None,
    ) -> str:
        """Build the full system prompt for a session."""

        parts: list[str] = []

        # 1. Platform identity
        parts.append(_PLATFORM_IDENTITY)

        # 2. Tool categories
        if tool_categories:
            cats = ", ".join(sorted(tool_categories))
            parts.append(f"Available tool categories: {cats}")

        # 4. Current date/time
        now = datetime.now(UTC)
        date_str = now.strftime("%A, %B %d, %Y at %H:%M UTC")
        parts.append(f"Current date and time: {date_str}")

        # 5. Output guidelines
        parts.append(_OUTPUT_GUIDELINES)

        return "\n\n".join(parts)

    async def _load_preferences(
        self,
        session_db: AsyncSession,
    ) -> str | None:
        """Load user preference memory entries and format as text."""
        repo = GenericRepository(session_db, MemoryModel)
        memories = await repo.find(kind="preference")
        if not memories:
            return None
        return "; ".join(m.content for m in memories)
