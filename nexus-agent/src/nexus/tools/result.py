"""ToolResult — outcome of a single tool execution."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

TOOL_RESULT_STATUS = Literal["success", "error", "timeout", "validation_error", "interrupted"]

RAW_RESPONSE_MAX_CHARS: int = 2000


class ToolResult(BaseModel):
    """Outcome of a single tool execution returned to the agent."""

    tool_id: uuid.UUID = Field(description="Executed tool identifier")
    tool_name: str = Field(description="Executed tool name")
    status: TOOL_RESULT_STATUS = Field(description="Execution outcome")
    http_status: int | None = Field(default=None, description="HTTP response status code")
    data: dict[str, Any] | None = Field(default=None, description="Parsed response body")
    error: str | None = Field(default=None, description="Error message if failed")
    duration_ms: int = Field(default=0, description="Wall-clock execution time in ms")
    retried: bool = Field(default=False, description="Whether retries were attempted")
    raw_response_excerpt: str | None = Field(
        default=None, description="Truncated raw response text"
    )
    response_headers: dict[str, str] | None = Field(
        default=None, description="Response HTTP headers (canonicalised lowercase)"
    )

    @field_validator("raw_response_excerpt", mode="before")
    @classmethod
    def _truncate(cls, v: str | None) -> str | None:
        if v and len(v) > RAW_RESPONSE_MAX_CHARS:
            return v[:RAW_RESPONSE_MAX_CHARS] + "..."
        return v
