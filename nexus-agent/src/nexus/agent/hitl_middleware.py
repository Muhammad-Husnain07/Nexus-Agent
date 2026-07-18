"""HITL middleware — wraps ``ToolExecutor.execute`` with approval gating.

Replaces the inline approval logic in ``execute_step.py``.  Handles the
full approval lifecycle: check → interrupt → validate edits → reject →
execute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import jsonschema
import structlog

from nexus.agent import hitl
from nexus.agent.errors import ApprovalRejected
from nexus.config.settings import AgentSettings
from nexus.redis_client.pubsub import EventBus, agent_channel
from nexus.tools.executor import ExecutionContext, ToolExecutor
from nexus.tools.result import ToolResult
from nexus.tools.schemas import ToolRead

logger = structlog.get_logger("nexus.agent.hitl_middleware")


@dataclass
class ApprovalDecision:
    """Result of the approval check + interrupt cycle."""

    action: str = "approve"
    edited_inputs: dict[str, Any] | None = field(default=None)


class HITLMiddleware:
    """Middleware that gates tool execution behind human approval.

    Usage in a node function::

        middleware = HITLMiddleware(executor, settings)
        try:
            result = await middleware.execute(
                tool_read=tool_read,
                plan_step=step,
                func_args=func_args,
                context=ctx,
                event_bus=event_bus,
                session_id=session_id,
            )
        except ApprovalRejected:
            # mark step skipped, ask user for alternative
            ...
    """

    def __init__(
        self,
        executor: ToolExecutor,
        settings: AgentSettings | None = None,
    ) -> None:
        self._executor = executor
        self._settings = settings

    async def execute(  # noqa: PLR0913
        self,
        tool_read: ToolRead,
        plan_step: dict[str, Any] | None,
        func_args: dict[str, Any],
        context: ExecutionContext,
        event_bus: EventBus | None = None,
        session_id: str | None = None,
        db_session: Any = None,
    ) -> ToolResult:
        """Gate *func_args* through HITL, then call ``ToolExecutor.execute``.

        Returns:
            The ``ToolResult`` from the underlying executor.

        Raises:
            ApprovalRejected: When the human rejects the tool call.
            ValueError: When edited inputs fail schema validation.
        """
        decision = await self._check_and_interrupt(
            tool_read=tool_read,
            plan_step=plan_step,
            func_args=func_args,
            event_bus=event_bus,
            session_id=session_id,
        )

        resolved_args = decision.edited_inputs if decision.action == "edit" else func_args

        return await self._executor.execute(
            tool_read,
            resolved_args,
            context,
            skip_approval=True,
            session=db_session,
        )

    async def _check_and_interrupt(  # noqa: PLR0913
        self,
        tool_read: ToolRead,
        plan_step: dict[str, Any] | None,
        func_args: dict[str, Any],
        event_bus: EventBus | None = None,
        session_id: str | None = None,
    ) -> ApprovalDecision:
        """Run the approval check and, if needed, the interrupt cycle.

        Returns:
            An ``ApprovalDecision`` indicating what to do next.

        Raises:
            ApprovalRejected: When the human rejects the tool call.
            ValueError: When edited inputs fail schema validation.
        """
        if not hitl.requires_approval(tool_read, plan_step, self._settings):
            return ApprovalDecision(action="approve")

        payload = hitl.build_approval_payload(tool_read, plan_step, func_args)

        if event_bus and session_id:
            await event_bus.publish(
                agent_channel(session_id),
                payload,
            )

        try:
            decision = hitl.interrupt_for_approval(payload)
        except Exception:
            decision = {"action": "reject", "edited_inputs": None, "comment": None}

        action = decision.get("action", "approve")

        if action == "reject":
            comment = decision.get("comment") or "Rejected by user"
            logger.info("hitl_middleware.rejected", tool=tool_read.name, comment=comment)
            raise ApprovalRejected(comment)

        if action == "edit":
            edited = decision.get("edited_inputs")
            if edited is not None:
                self._validate_edited_inputs(edited, tool_read.input_schema)
                return ApprovalDecision(action="edit", edited_inputs=edited)

        return ApprovalDecision(action="approve")

    @staticmethod
    def _validate_edited_inputs(
        inputs: dict[str, Any],
        schema: dict[str, Any] | None,
    ) -> None:
        """Validate *inputs* against the tool's JSON Schema.

        Raises:
            ValueError: If validation fails.
        """
        if not schema or schema == {"type": "object", "properties": {}}:
            return
        try:
            jsonschema.validate(inputs, schema)
        except jsonschema.ValidationError as exc:
            raise ValueError(f"Edited inputs failed validation: {exc}") from exc
