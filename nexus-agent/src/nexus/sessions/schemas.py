"""Pydantic request/response models for Session and Message CRUD."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    """Request to create a new session."""

    title: str = Field(default="New Session", max_length=512, description="Session title")
    metadata_: dict[str, Any] | None = Field(
        default=None, alias="metadata", description="Arbitrary session metadata"
    )


class SessionUpdate(BaseModel):
    """Request to update session fields."""

    title: str | None = Field(default=None, max_length=512, description="Session title")
    status: str | None = Field(
        default=None, pattern="^(active|archived)$", description="Session status"
    )
    metadata_: dict[str, Any] | None = Field(
        default=None, alias="metadata", description="Arbitrary session metadata"
    )


class SessionRead(BaseModel):
    """Full session response."""

    id: uuid.UUID
    title: str
    status: str
    metadata_: dict[str, Any] | None = Field(alias="metadata")
    created_at: datetime
    updated_at: datetime
    message_count: int = Field(default=0, description="Number of messages in the session")

    model_config = {"from_attributes": True, "populate_by_name": True}


class SessionList(BaseModel):
    """Paginated session list."""

    items: list[SessionRead]
    total: int
    page: int
    page_size: int


class MessageCreate(BaseModel):
    """Request to add a message to a session."""

    role: str = Field(pattern="^(user|assistant|tool|system)$", description="Message role")
    content: dict[str, Any] = Field(description="Message content (JSON)")
    tool_calls: list[dict[str, Any]] | None = Field(
        default=None, description="Tool call invocations"
    )
    parent_id: uuid.UUID | None = Field(default=None, description="Parent message ID for branching")


class MessageRead(BaseModel):
    """Full message response."""

    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: dict[str, Any] | None
    tool_calls: list[dict[str, Any]] | None
    parent_id: uuid.UUID | None = Field(alias="parent_message_id")
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class MessageList(BaseModel):
    """Paginated message list."""

    items: list[MessageRead]
    total: int
    page: int
    page_size: int


class ForkRequest(BaseModel):
    """Request to fork a session at a given message."""

    message_id: uuid.UUID = Field(description="Copy history up to (and including) this message")
    new_title: str | None = Field(
        default=None, max_length=512, description="Title for the new session"
    )
