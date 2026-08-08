"""NexusRuntime — programmatic embedding SDK for the Agent Orchestration Runtime.

Developers embed the runtime into their Python applications without running
the FastAPI server. ``NexusRuntime`` wraps the existing components
(AgentRunner, ToolRegistry, TaskRegistry, template engine) behind a single
importable, dependency-injected API.

Usage::

    from nexus.runtime import NexusRuntime

    runtime = await NexusRuntime.create()
    tool = await runtime.register_capability(
        name="get_invoice",
        endpoint_url="https://api.example.com/invoices/{invoice_id}",
        http_method="GET",
        purpose="Fetch an invoice by id",
        input_schema={"type": "object", "properties": {"invoice_id": {"type": "string"}}},
    )
    wf = await runtime.register_workflow(
        name="invoice_approval",
        trigger_intent_pattern="approve invoice",
        steps=[{"id": "step_1", "description": "Fetch", "intent": "get_invoice"}],
    )
    session_id = await runtime.create_session(title="Support")
    events = []
    async for event in runtime.chat(session_id, "Get invoice 42"):
        events.append(event)

Everything is metadata-driven — no capability, tool, or workflow name is
hardcoded here. Components are lazily created with sensible defaults and can
be injected for tests.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import structlog

from nexus.config.settings import get_settings
from nexus.db.base import async_session as _session_factory

logger = structlog.get_logger("nexus.runtime")


class NexusRuntime:
    """Programmatic entry point for embedding the Nexus runtime."""

    def __init__(
        self,
        *,
        runner: Any = None,
        tool_registry: Any = None,
        task_registry: Any = None,
        queue: Any = None,
        session_factory: Any = None,
        llm: Any = None,
    ) -> None:
        """Create a runtime with injectable components (all optional).

        Args:
            runner: AgentRunner instance (default: built lazily).
            tool_registry: ToolRegistry instance (default: built lazily).
            task_registry: TaskRegistry instance (default: built lazily).
            queue: TaskQueue instance (default: RedisStreamsQueue).
            session_factory: DB session factory (default: app factory).
            llm: LLMClient instance (default: created lazily).
        """
        self._runner = runner
        self._tool_registry = tool_registry
        self._task_registry = task_registry
        self._queue = queue
        self._session_factory = session_factory or _session_factory
        self._llm = llm
        self._session_service: Any = None

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    async def create(cls, **kwargs: Any) -> "NexusRuntime":
        """Create a runtime with all default components wired.

        Args:
            **kwargs: Forwarded to ``NexusRuntime.__init__``.

        Returns:
            A fully-wired runtime instance.
        """
        runtime = cls(**kwargs)
        await runtime._ensure_core()  # noqa: SLF001
        return runtime

    async def _ensure_core(self) -> None:
        from nexus.agent.runner import AgentRunner  # noqa: PLC0415
        from nexus.memory.checkpointer import get_checkpointer  # noqa: PLC0415
        from nexus.providers.queue.redis_streams import RedisStreamsQueue  # noqa: PLC0415
        from nexus.redis_client import EventBus, get_redis_client  # noqa: PLC0415
        from nexus.tasks.registry import TaskRegistry  # noqa: PLC0415
        from nexus.tools.executor import ToolExecutor  # noqa: PLC0415
        from nexus.tools.registry import ToolRegistry  # noqa: PLC0415

        if self._llm is None:
            from nexus.llm.client import LLMClient

            self._llm = LLMClient()

        if self._tool_registry is None:
            self._tool_registry = ToolRegistry(llm_client=self._llm)

        redis = get_redis_client()
        event_bus = EventBus(redis) if redis else None

        if self._queue is None:
            self._queue = RedisStreamsQueue()

        if self._task_registry is None:
            self._task_registry = TaskRegistry()

        checkpointer = None
        settings = get_settings()
        if settings.memory.checkpointer_type == "postgres":
            try:
                checkpointer = await get_checkpointer()
            except Exception as exc:
                logger.warning("runtime.checkpointer_unavailable", error=str(exc))

        if self._runner is None:
            executor = ToolExecutor(event_bus=event_bus)
            self._runner = AgentRunner(
                llm_client=self._llm,
                tool_executor=executor,
                event_bus=event_bus,
                session_factory=self._session_factory,
                checkpointer=checkpointer,
            )

    # ------------------------------------------------------------------
    # Capabilities (tools)
    # ------------------------------------------------------------------

    async def register_capability(self, **fields: Any) -> dict[str, Any]:
        """Register a capability (tool) with the runtime.

        Args:
            **fields: ToolCreate fields (name, endpoint_url, http_method,
                purpose, input_schema, output_schema, risk_level, ...).

        Returns:
            The registered capability as a dict.

        Raises:
            ValueError: If name or endpoint_url are missing.
        """
        if not fields.get("name") or not fields.get("endpoint_url"):
            raise ValueError("register_capability requires name and endpoint_url")
        await self._ensure_core()
        from nexus.tools.schemas import ToolCreate

        data = ToolCreate(**fields)
        async with self._session_factory() as session:
            tool = await self._tool_registry.register(session, data)  # type: ignore[union-attr]
            await session.commit()
            from nexus.tools.registry import _refresh_resolution_indexes

            await _refresh_resolution_indexes()
            return tool.model_dump() if hasattr(tool, "model_dump") else tool

    async def list_capabilities(self, **filters: Any) -> list[dict[str, Any]]:
        """List registered capabilities.

        Args:
            **filters: Filter kwargs (name, enabled, ...).

        Returns:
            List of capability dicts.
        """
        await self._ensure_core()
        async with self._session_factory() as session:
            tools = await self._tool_registry.list(session=session, **filters)  # type: ignore[union-attr]
            return [t.model_dump() if hasattr(t, "model_dump") else t for t in tools]

    # ------------------------------------------------------------------
    # Workflows
    # ------------------------------------------------------------------

    async def register_workflow(
        self,
        *,
        name: str,
        steps: list[dict[str, Any]],
        trigger_intent_pattern: str = "",
        description: str = "",
        priority: int = 0,
        max_nodes: int = 10,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Register a deterministic workflow definition.

        Args:
            name: Unique workflow name.
            steps: Ordered step dicts (id, description, intent/capability/
                dynamic/workflow_ref, inputs, requires_input, question).
            trigger_intent_pattern: Pattern matched against user requests.
            description: Human-readable description.
            priority: Match priority (higher = matched first).
            max_nodes: Max steps before dynamic hand-off.
            enabled: Whether the workflow is active.

        Returns:
            The registered workflow as a dict.
        """
        from nexus.api.workflows import WorkflowDefinitionCreate, _workflow_to_dict
        from nexus.db.models.workflow_definition import WorkflowDefinition

        payload = WorkflowDefinitionCreate(
            name=name,
            description=description,
            trigger_intent_pattern=trigger_intent_pattern,
            steps=steps,
            priority=priority,
            max_nodes=max_nodes,
            enabled=enabled,
        )
        async with self._session_factory() as session:
            existing = await session.execute(
                _select_workflow_by_name(name)
            )
            if existing.scalars().first() is not None:
                raise ValueError(f"Workflow name already exists: {name}")
            wf = WorkflowDefinition(
                name=payload.name,
                description=payload.description,
                trigger_intent_pattern=payload.trigger_intent_pattern,
                steps=[s.model_dump() for s in payload.steps],
                priority=payload.priority,
                max_nodes=payload.max_nodes,
                enabled=payload.enabled,
                version=1,
            )
            session.add(wf)
            await session.commit()
            await session.refresh(wf)
            return _workflow_to_dict(wf)

    async def list_workflows(self, enabled: bool | None = None) -> list[dict[str, Any]]:
        """List workflow definitions.

        Args:
            enabled: Filter by enabled state when not None.

        Returns:
            List of workflow dicts.
        """
        from nexus.api.workflows import _workflow_to_dict
        from nexus.db.models.workflow_definition import WorkflowDefinition

        async with self._session_factory() as session:
            stmt = _select_workflow_by_name("")
            stmt = _workflow_list_stmt(enabled)
            result = await session.execute(stmt)
            return [_workflow_to_dict(w) for w in result.scalars().all()]

    async def delete_workflow(self, workflow_id: str) -> None:
        """Delete a workflow definition by id.

        Args:
            workflow_id: Workflow definition UUID string.
        """
        from nexus.db.models.workflow_definition import WorkflowDefinition

        async with self._session_factory() as session:
            wf = await session.get(WorkflowDefinition, uuid.UUID(workflow_id))
            if wf is None:
                raise ValueError(f"Workflow not found: {workflow_id}")
            await session.delete(wf)
            await session.commit()

    # ------------------------------------------------------------------
    # Sessions & chat
    # ------------------------------------------------------------------

    async def create_session(self, title: str = "Runtime session") -> str:
        """Create a conversation session.

        Args:
            title: Session title.

        Returns:
            The session id string.
        """
        from nexus.sessions.schemas import SessionCreate  # noqa: PLC0415
        from nexus.sessions.service import SessionService  # noqa: PLC0415

        if self._session_service is None:
            from nexus.sessions.context_window import ContextWindowManager  # noqa: PLC0415
            from nexus.sessions.repository import (  # noqa: PLC0415
                MessageRepository,
                SessionRepository,
            )
            from nexus.sessions.service import SessionService  # noqa: PLC0415

            async with self._session_factory() as db:
                self._session_service = SessionService(
                    session_repo=SessionRepository(db),
                    message_repo=MessageRepository(db),
                    context_window=ContextWindowManager(llm_client=self._llm),
                )
        session = await self._session_service.create_session(
            data=SessionCreate(title=title)
        )
        return str(session.id)

    async def chat(
        self,
        session_id: str,
        message: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream agent events for a chat message (SSE-equivalent dicts).

        Args:
            session_id: Session id string.
            message: User message.

        Yields:
            AgentEvent dicts (type, ts, payload).
        """
        await self._ensure_core()
        async for event in self._runner.invoke(session_id=session_id, user_message=message):  # type: ignore[union-attr]
            yield event.to_dict()

    # ------------------------------------------------------------------
    # Long-running tasks
    # ------------------------------------------------------------------

    async def create_task(
        self,
        task_type: str,
        payload: dict[str, Any] | None = None,
        session_id: str | None = None,
        max_attempts: int = 3,
        schedule_cron: str | None = None,
        next_run_at: str | None = None,
    ) -> dict[str, Any]:
        """Create (and enqueue) a background task.

        Args:
            task_type: Registered task type (e.g. workflow_run).
            payload: Task input payload.
            session_id: Originating session id.
            max_attempts: Max attempts before failure.
            schedule_cron: Cron expression for recurring runs.
            next_run_at: ISO timestamp for one-shot scheduling.

        Returns:
            The task record as a dict.
        """
        await self._ensure_core()
        from datetime import UTC, datetime

        next_run = None
        if next_run_at:
            next_run = datetime.fromisoformat(next_run_at.replace("Z", "+00:00"))
            if next_run.tzinfo is None:
                next_run = next_run.replace(tzinfo=UTC)

        task = await self._task_registry.create(  # type: ignore[union-attr]
            task_type=task_type,
            payload=payload or {},
            session_id=session_id,
            max_attempts=max_attempts,
            schedule_cron=schedule_cron,
            next_run_at=next_run,
        )
        if not schedule_cron and next_run is None:
            await self._queue.enqueue(task["id"], payload or {})  # type: ignore[union-attr]
            task = await self._task_registry.update_status(task["id"], "queued") or task  # type: ignore[union-attr]
        return task

    async def get_task(self, task_id: str) -> dict[str, Any]:
        """Get a task record by id.

        Args:
            task_id: Task id string.

        Returns:
            The task record as a dict.
        """
        await self._ensure_core()
        task = await self._task_registry.get(task_id)  # type: ignore[union-attr]
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        return task

    async def cancel_task(self, task_id: str) -> dict[str, Any]:
        """Request cancellation of a task.

        Args:
            task_id: Task id string.

        Returns:
            The updated task record.
        """
        await self._ensure_core()
        task = await self._task_registry.request_cancel(task_id)  # type: ignore[union-attr]
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        return task

    async def close(self) -> None:
        """Release resources held by the runtime.

        Cancels background tasks and closes the session service. The
        module-level graph cache and DB engine are shared process-wide and
        are intentionally not torn down here.
        """
        if self._session_service is not None:
            svc = self._session_service
            self._session_service = None
            try:
                close = getattr(svc, "close", None)
                if close is not None:
                    await close()
            except Exception as exc:
                logger.warning("runtime.session_service_close_failed", error=str(exc))
        logger.info("runtime.closed")


# ----------------------------------------------------------------------------
# Module-level helpers (kept local to avoid extra imports at runtime)
# ----------------------------------------------------------------------------


def _select_workflow_by_name(name: str) -> Any:
    from sqlalchemy import select

    from nexus.db.models.workflow_definition import WorkflowDefinition

    return select(WorkflowDefinition).where(WorkflowDefinition.name == name)


def _workflow_list_stmt(enabled: bool | None) -> Any:
    from sqlalchemy import select

    from nexus.db.models.workflow_definition import WorkflowDefinition

    stmt = select(WorkflowDefinition).order_by(
        WorkflowDefinition.priority.desc(), WorkflowDefinition.name
    )
    if enabled is not None:
        stmt = stmt.where(WorkflowDefinition.enabled == enabled)  # noqa: E712
    return stmt
