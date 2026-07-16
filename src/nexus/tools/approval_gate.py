"""Approval gate — human-in-the-loop interrupt for tool execution.

Before executing a tool with ``requires_approval=True`` or matching
``hitl_tool_patterns``, raise an ``ApprovalRequiredInterrupt``. The LangGraph
supervisor catches this and calls ``interrupt()`` (wired in Phase 11).
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from pydantic import BaseModel, Field

from nexus.config.settings import AgentSettings
from nexus.tools.schemas import ToolRead


class ApprovalRequiredInterrupt(Exception):
    """Raised when a tool call requires human approval before execution.

    The agent graph catches this and suspends via LangGraph ``interrupt()``
    to await human feedback.
    """

    def __init__(  # noqa: PLR0913
        self,
        tool_name: str,
        inputs: dict[str, Any],
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        agent_run_id: uuid.UUID | None = None,
    ) -> None:
        self.tool_name = tool_name
        self.inputs = inputs
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.session_id = session_id
        self.agent_run_id = agent_run_id
        super().__init__(
            f"Tool '{tool_name}' requires human approval. "
            f"session_id={session_id}, tenant_id={tenant_id}"
        )

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-serialisable payload for the interrupt."""
        return {
            "type": "approval_required",
            "tool_name": self.tool_name,
            "inputs": self.inputs,
            "tenant_id": str(self.tenant_id),
            "user_id": str(self.user_id),
            "session_id": str(self.session_id),
            "agent_run_id": str(self.agent_run_id) if self.agent_run_id else None,
        }


class ApprovalCheckResult(BaseModel):
    """Result of an approval check."""

    required: bool = Field(description="Whether human approval is required")
    reason: str | None = Field(default=None, description="Why approval is required")


def check_approval_required(  # noqa: PLR0913
    tool: ToolRead,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    agent_run_id: uuid.UUID | None = None,
    settings: AgentSettings | None = None,
    plan_step: dict[str, Any] | None = None,
) -> ApprovalCheckResult:
    """Check whether a tool call needs human approval.

    Approval is required if any of these are true:
    1. The tool's ``requires_approval`` flag is True.
    2. The plan step has ``is_destructive=True``.
    3. The tool's ``risk_level`` is ``"medium"`` or ``"high"``.
    4. ``settings.hitl_default`` is True (global default).
    5. The tool name matches any regex in ``settings.hitl_tool_patterns``.

    When approval is required, the caller should raise
    ``ApprovalRequiredInterrupt``.

    Args:
        tool: The tool being invoked.
        tenant_id: Current tenant.
        user_id: Current user.
        session_id: Current session.
        agent_run_id: Optional agent run identifier.
        settings: Agent settings. If None, uses defaults from ``get_settings()``.
        plan_step: The current plan step (optional). Used to check
            ``is_destructive``.

    Returns:
        ``ApprovalCheckResult`` indicating whether approval is needed and why.
    """
    if settings is None:
        from nexus.config.settings import get_settings  # noqa: PLC0415

        settings = get_settings().agent

    if tool.requires_approval:
        return ApprovalCheckResult(
            required=True,
            reason=f"Tool '{tool.name}' has requires_approval=True",
        )

    if plan_step and plan_step.get("is_destructive", False):
        return ApprovalCheckResult(
            required=True,
            reason=f"Plan step '{plan_step.get('id', '?')}' is destructive",
        )

    if tool.risk_level in ("medium", "high"):
        return ApprovalCheckResult(
            required=True,
            reason=f"Tool '{tool.name}' risk_level is '{tool.risk_level}'",
        )

    if settings.hitl_default:
        return ApprovalCheckResult(
            required=True,
            reason="Global HITL default is enabled",
        )

    for pattern in settings.hitl_tool_patterns:
        if re.search(pattern, tool.name):
            return ApprovalCheckResult(
                required=True,
                reason=f"Tool '{tool.name}' matches HITL pattern '{pattern}'",
            )

    return ApprovalCheckResult(required=False, reason=None)
