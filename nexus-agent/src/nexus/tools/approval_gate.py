"""Approval gate — human-in-the-loop interrupt for tool execution."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from nexus.config.settings import AgentSettings
from nexus.tools.schemas import ToolRead


class ApprovalRequiredInterrupt(Exception):
    """Raised when a tool call requires human approval before execution."""

    def __init__(  # noqa: PLR0913
        self,
        tool_name: str,
        inputs: dict[str, Any],
        session_id: uuid.UUID,
        agent_run_id: uuid.UUID | None = None,
    ) -> None:
        self.tool_name = tool_name
        self.inputs = inputs
        self.session_id = session_id
        self.agent_run_id = agent_run_id
        super().__init__(
            f"Tool '{tool_name}' requires human approval. "
            f"session_id={session_id}"
        )

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-serialisable payload for the interrupt."""
        return {
            "type": "approval_required",
            "tool_name": self.tool_name,
            "inputs": self.inputs,
            "session_id": str(self.session_id),
            "agent_run_id": str(self.agent_run_id) if self.agent_run_id else None,
        }


class ApprovalCheckResult(BaseModel):
    """Result of an approval check."""

    required: bool = Field(description="Whether human approval is required")
    reason: str | None = Field(default=None, description="Why approval is required")


def check_approval_required(  # noqa: PLR0913
    tool: ToolRead,
    session_id: uuid.UUID,
    agent_run_id: uuid.UUID | None = None,
    settings: AgentSettings | None = None,
    plan_step: dict[str, Any] | None = None,
) -> ApprovalCheckResult:
    """Check whether a tool call needs human approval."""
    from nexus.agent.hitl import requires_approval  # noqa: PLC0415

    needed = requires_approval(tool, plan_step, settings)
    return ApprovalCheckResult(
        required=needed,
        reason="HITL approval required" if needed else None,
    )
