"""Pydantic request/response models for the agent API endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


class AgentInvokeRequest(BaseModel):
    """Request to invoke the agent with a user message."""

    session_id: uuid.UUID = Field(description="Conversation session ID")
    message: str = Field(description="User message", min_length=1)


class AgentInvokeResponse(BaseModel):
    """Response from a synchronous agent invocation."""

    session_id: uuid.UUID
    final_response: str | None = Field(default=None, description="Final agent response text")
    requires_approval: bool = Field(
        default=False, description="Whether execution is paused for approval"
    )
    approval_payload: dict[str, Any] | None = Field(
        default=None, description="Details of the pending approval request"
    )
    interrupted: bool = Field(
        default=False, description="Whether execution paused at an interrupt"
    )
    error: str | None = Field(default=None, description="Error message if execution failed")
    events: list[dict[str, Any]] = Field(
        default_factory=list, description="All state update events from the run"
    )


class AgentStreamEvent(BaseModel):
    """Event payload for SSE streaming responses."""

    type: str = Field(description="Event type identifier")
    data: dict[str, Any] = Field(default_factory=dict, description="Event payload data")
    ts: str = Field(default="", description="ISO-8601 timestamp")


class ApprovalAction(BaseModel):
    """User's approval decision for a pending tool call."""

    approved: bool = Field(
        default=True,
        description="(Backward compat) Whether the tool call is approved",
    )
    modified_inputs: dict[str, Any] | None = Field(
        default=None,
        description="(Backward compat) Optionally modified input parameters",
    )
    action: str | None = Field(
        default=None,
        description="Explicit action: approve | reject | edit",
    )
    edited_inputs: dict[str, Any] | None = Field(
        default=None,
        description="Edited tool inputs (used when action=edit)",
    )
    comment: str | None = Field(
        default=None,
        description="Optional human comment on the decision",
    )


class AgentResumeResponse(BaseModel):
    """Response after resuming from an approval interrupt."""

    session_id: uuid.UUID
    status: str = Field(
        description="Result status: completed, interrupted, or error"
    )
    final_response: str | None = Field(
        default=None, description="Final agent response after resume"
    )
    requires_approval: bool = Field(
        default=False, description="Whether execution paused again for approval"
    )
    approval_payload: dict[str, Any] | None = Field(
        default=None, description="New approval payload if interrupted again"
    )
    error: str | None = Field(default=None, description="Error message if resume failed")


class AgentStateResponse(BaseModel):
    """Snapshot of the current agent state for a session."""

    session_id: uuid.UUID
    status: str = Field(description="Run status: running, paused, completed, error")
    current_node: str | None = Field(default=None, description="Currently executing node")
    pending_approval: dict[str, Any] | None = Field(
        default=None, description="Pending approval request if paused"
    )
    final_response: str | None = Field(default=None, description="Final response if completed")
    error: str | None = Field(default=None, description="Error if run failed")
