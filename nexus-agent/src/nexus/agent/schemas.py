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
    error: str | None = Field(default=None, description="Error message if execution failed")
    events: list[dict[str, Any]] = Field(
        default_factory=list, description="All state update events from the run"
    )


class AgentStreamEvent(BaseModel):
    """Event payload for SSE streaming responses."""

    type: str = Field(description="Event type identifier")
    data: dict[str, Any] = Field(default_factory=dict, description="Event payload data")
    ts: str = Field(default="", description="ISO-8601 timestamp")


class AgentStateResponse(BaseModel):
    """Snapshot of the current agent state for a session."""

    session_id: uuid.UUID
    status: str = Field(description="Run status: running, paused, completed, error")
    current_node: str | None = Field(default=None, description="Currently executing node")
    final_response: str | None = Field(default=None, description="Final response if completed")
    error: str | None = Field(default=None, description="Error if run failed")
