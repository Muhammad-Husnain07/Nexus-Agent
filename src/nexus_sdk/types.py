"""Typed Pydantic models for the Nexus Agent SDK."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolSchema(BaseModel):
    """A tool definition matching the API's ToolCreate schema."""

    name: str = Field(description="Unique tool name (per tenant)")
    description: str = Field(default="", description="Human-readable description")
    purpose: str = Field(default="", description="What the tool does and when to use it")
    endpoint_url: str = Field(default="", description="API endpoint URL")
    http_method: str = Field(default="GET", description="HTTP method")
    auth_type: str = Field(default="none", description="Authentication type")
    auth_ref: str = Field(default="", description="Reference to stored auth config")
    input_schema: dict[str, Any] = Field(default_factory=dict, description="JSON Schema for input")
    output_schema: dict[str, Any] = Field(default_factory=dict, description="JSON Schema for output")
    tags: list[str] = Field(default_factory=list, description="Categorization tags")
    category: str = Field(default="general", description="Functional category")
    requires_approval: bool = Field(default=False, description="Requires HITL approval")
    risk_level: Literal["low", "medium", "high"] = Field(default="low")
    enabled: bool = Field(default=True)


class SessionInfo(BaseModel):
    """Conversation session information."""

    id: uuid.UUID = Field(description="Session UUID")
    tenant_id: uuid.UUID = Field(description="Tenant UUID")
    user_id: uuid.UUID = Field(description="User UUID")
    title: str = Field(description="Session title")
    status: str = Field(description="active or archived")
    created_at: datetime = Field(description="Creation timestamp")
    updated_at: datetime = Field(description="Last update timestamp")
    metadata_: dict[str, Any] = Field(default_factory=dict)


class ChatEvent(BaseModel):
    """A single event in a chat SSE stream."""

    type: str = Field(description="Event type: plan_created, final_response, etc.")
    ts: str = Field(description="ISO-8601 timestamp")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event data")


class ApprovalAction(BaseModel):
    """Decision payload for approving/rejecting/editing a tool call."""

    action: str = Field(description="approve, reject, or edit")
    comment: str | None = Field(default=None, description="Human comment")
    edited_inputs: dict[str, Any] | None = Field(default=None, description="Modified inputs (for edit action)")
