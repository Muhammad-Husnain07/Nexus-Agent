"""Pydantic schemas for tool registration, discovery, and search."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ToolExample(BaseModel):
    """Example invocation of a tool."""

    user_prompt: str = Field(description="Example user message that would trigger this tool")
    expected_tool: str = Field(description="Tool name expected to be selected")
    sample_input: dict[str, Any] = Field(
        default_factory=dict, description="Sample input parameters"
    )
    sample_output: dict[str, Any] = Field(
        default_factory=dict, description="Sample output response"
    )


class ToolCreate(BaseModel):
    """Request body for registering a new tool."""

    name: str = Field(description="Unique tool name (per tenant)")
    description: str = Field(default="", description="Human-readable description")
    purpose: str = Field(default="", description="What the tool does and when to use it")
    endpoint_url: str = Field(default="", description="API endpoint URL")
    http_method: str = Field(default="GET", description="HTTP method")
    auth_type: str = Field(default="none", description="Authentication type")
    auth_ref: str = Field(default="", description="Reference to stored auth config")
    input_schema: dict[str, Any] = Field(default_factory=dict, description="JSON Schema for input")
    output_schema: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema for output"
    )
    validation_rules: dict[str, Any] = Field(
        default_factory=dict, description="Business validation rules"
    )
    examples: list[ToolExample] = Field(default_factory=list, description="Example invocations")
    tags: list[str] = Field(default_factory=list, description="Categorization tags")
    category: str = Field(default="general", description="Functional category")
    requires_approval: bool = Field(default=False, description="Requires HITL approval")
    risk_level: str = Field(default="low", description="Risk level: low | medium | high")
    enabled: bool = Field(default=True, description="Whether the tool is active")
    tenant_public: bool = Field(
        default=False, description="Visible to all tenants when true"
    )
    idempotent: bool = Field(
        default=False, description="Whether the tool supports idempotent execution (safe to retry)"
    )


class ToolUpdate(BaseModel):
    """Request body for updating an existing tool. All fields optional."""

    name: str | None = Field(default=None, description="Unique tool name (per tenant)")
    description: str | None = Field(default=None, description="Human-readable description")
    purpose: str | None = Field(default=None, description="What the tool does and when to use it")
    endpoint_url: str | None = Field(default=None, description="API endpoint URL")
    http_method: str | None = Field(default=None, description="HTTP method")
    auth_type: str | None = Field(default=None, description="Authentication type")
    auth_ref: str | None = Field(default=None, description="Reference to stored auth config")
    input_schema: dict[str, Any] | None = Field(default=None, description="JSON Schema for input")
    output_schema: dict[str, Any] | None = Field(default=None, description="JSON Schema for output")
    validation_rules: dict[str, Any] | None = Field(
        default=None, description="Business validation rules"
    )
    examples: list[ToolExample] | None = Field(default=None, description="Example invocations")
    tags: list[str] | None = Field(default=None, description="Categorization tags")
    category: str | None = Field(default=None, description="Functional category")
    requires_approval: bool | None = Field(default=None, description="Requires HITL approval")
    risk_level: str | None = Field(default=None, description="Risk level: low | medium | high")
    enabled: bool | None = Field(default=None, description="Whether the tool is active")


class ToolRead(BaseModel):
    """Full tool definition returned by the API."""

    id: uuid.UUID = Field(description="Unique tool identifier")
    tenant_id: uuid.UUID = Field(description="Owning tenant")
    name: str = Field(description="Unique tool name (per tenant)")
    description: str = Field(description="Human-readable description")
    purpose: str = Field(description="What the tool does and when to use it")
    endpoint_url: str = Field(description="API endpoint URL")
    http_method: str = Field(description="HTTP method")
    auth_type: str = Field(description="Authentication type")
    auth_ref: str = Field(description="Reference to stored auth config")
    input_schema: dict[str, Any] = Field(description="JSON Schema for input")
    output_schema: dict[str, Any] = Field(description="JSON Schema for output")
    validation_rules: dict[str, Any] = Field(description="Business validation rules")
    examples: list[dict[str, Any]] = Field(description="Example invocations")
    tags: list[str] = Field(description="Categorization tags")
    category: str = Field(description="Functional category")
    requires_approval: bool = Field(description="Requires HITL approval")
    risk_level: str = Field(description="Risk level")
    enabled: bool = Field(description="Whether the tool is active")
    tenant_public: bool = Field(default=False, description="Visible to all tenants")
    idempotent: bool = Field(default=False, description="Supports idempotent execution")
    version: int = Field(description="Tool definition version")
    created_at: datetime = Field(description="Creation timestamp")
    updated_at: datetime = Field(description="Last update timestamp")
    embedding: list[float] | None = Field(default=None, description="Semantic embedding vector")

    model_config = {"from_attributes": True}


class ToolList(BaseModel):
    """Paginated list of tools."""

    items: list[ToolRead] = Field(description="Tools on this page")
    total: int = Field(description="Total number of matching tools")
    page: int = Field(description="Current page number")
    page_size: int = Field(description="Number of items per page")


class ToolSearchResult(BaseModel):
    """A single tool result from semantic search."""

    tool: ToolRead = Field(description="The matching tool")
    score: float = Field(description="Cosine similarity score (0-1)")


class ToolVersionDiff(BaseModel):
    """Differences between two versions of a tool."""

    tool_id: uuid.UUID = Field(description="Tool identifier")
    old_version: int = Field(description="Previous version number")
    new_version: int = Field(description="Current version number")
    changed_fields: list[str] = Field(description="Field names that changed")
