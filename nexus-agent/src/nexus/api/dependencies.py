"""FastAPI dependencies — user, services, and registries.

Provides reusable ``Annotated`` type aliases for dependency injection
across all API routers.
"""

from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.base import get_session
from nexus.llm.client import LLMClient
from nexus.redis_client.client import get_redis_client
from nexus.redis_client.pubsub import EventBus
from nexus.sessions.context_window import ContextWindowManager
from nexus.sessions.repository import MessageRepository, SessionRepository
from nexus.sessions.service import SessionService
from nexus.sessions.system_prompt import SystemPromptBuilder
from nexus.tools.discovery import DynamicToolSelector
from nexus.tools.executor import ToolExecutor
from nexus.tools.registry import ToolRegistry

logger = structlog.get_logger("nexus.api.dependencies")

__all__ = [
    "AgentRunnerDep",
    "SessionDep",
    "SessionServiceDep",
    "ToolRegistryDep",
]


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


async def get_session_service(db: Annotated[AsyncSession, Depends(get_session)]) -> SessionService:
    """Build a SessionService wired to the DB session and LLM."""
    from nexus.config.settings import get_settings  # noqa: PLC0415

    settings = get_settings()
    llm = LLMClient()
    return SessionService(
        session_repo=SessionRepository(db),
        message_repo=MessageRepository(db),
        context_window=ContextWindowManager(llm_client=llm, model=settings.llm.default_model),
        prompt_builder=SystemPromptBuilder(llm_client=llm),
        llm_client=llm,
        model=settings.llm.default_model,
    )


SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


async def get_agent_runner(request: Request) -> Any:
    """Build an AgentRunner wired to the application's services."""
    from nexus.agent.runner import AgentRunner  # noqa: PLC0415

    tool_registry: ToolRegistry = request.app.state.tool_registry
    llm = LLMClient()
    redis_client = get_redis_client()
    event_bus = EventBus(redis_client) if redis_client else None
    http_client = getattr(request.app.state, "http_client", None)
    tool_executor = ToolExecutor(event_bus=event_bus, http_client=http_client)
    tool_selector = DynamicToolSelector(
        registry=tool_registry,
        llm_client=llm,
    )
    # Resolve checkpointer from settings
    from nexus.config.settings import get_settings  # noqa: PLC0415
    from nexus.db.base import async_session  # noqa: PLC0415
    from nexus.memory.checkpointer import get_checkpointer  # noqa: PLC0415

    checkpointer = None
    settings = get_settings()
    if settings.memory.checkpointer_type == "postgres":
        try:
            checkpointer = await get_checkpointer()
            logger.info("checkpointer.wired", checkpointer_type="postgres")
        except Exception as exc:
            logger.warning("checkpointer.unavailable", error=str(exc))

    return AgentRunner(
        llm_client=llm,
        tool_selector=tool_selector,
        tool_executor=tool_executor,
        event_bus=event_bus,
        session_factory=async_session,
        checkpointer=checkpointer,
    )


AgentRunnerDep = Annotated[Any, Depends(get_agent_runner)]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


async def get_tool_registry(request: Request) -> ToolRegistry:
    """Return the cached tool registry from the application state."""
    return request.app.state.tool_registry


ToolRegistryDep = Annotated[ToolRegistry, Depends(get_tool_registry)]


# ---------------------------------------------------------------------------
# DB Session (re-exported from base for convenience)
# ---------------------------------------------------------------------------

SessionDep = Annotated[AsyncSession, Depends(get_session)]
