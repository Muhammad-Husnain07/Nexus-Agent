"""Pydantic request/response models for all API endpoints with OpenAPI examples."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(description="ok or degraded")
    version: str = Field(description="Application version")
    database: str | None = Field(default=None, description="Database connectivity status")
    redis: str | None = Field(default=None, description="Redis connectivity status")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "ok",
                "version": "0.1.0",
                "database": "ok",
                "redis": "ok",
            }
        }
    }


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str = Field(description="Human-readable error description")
    error_code: str | None = Field(default=None, description="Machine-readable error code")
    request_id: str | None = Field(default=None, description="Correlation ID for debugging")

    model_config = {
        "json_schema_extra": {
            "example": {
                "detail": "Session not found",
                "error_code": "NOT_FOUND",
                "request_id": "req_abc123",
            }
        }
    }


class ChatRequest(BaseModel):
    """Request payload for the chat endpoint."""

    message: str = Field(description="User message text", min_length=1, max_length=32000)
    attachments: list[str] | None = Field(
        default=None,
        description="Optional attachment URLs or file references",
        max_length=10,
    )
    stream: bool = Field(
        default=True,
        description="If true, response is SSE stream; if false, returns JSON",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "message": "Send an email to john@example.com saying the meeting is at 3pm",
                "stream": True,
            }
        }
    }


class ChatResponse(BaseModel):
    """Response from a non-streaming chat invocation."""

    session_id: str = Field(description="Conversation session ID")
    final_response: str | None = Field(default=None, description="Final agent response text")
    requires_approval: bool = Field(
        default=False, description="Whether execution is paused for HITL approval"
    )
    approval_payload: dict[str, Any] | None = Field(
        default=None, description="Details of the pending approval request"
    )
    interrupted: bool = Field(default=False, description="Whether execution paused at an interrupt")
    error: str | None = Field(default=None, description="Error message if execution failed")
    events: list[dict[str, Any]] = Field(
        default_factory=list, description="All state update events from the run"
    )
    request_id: str | None = Field(default=None, description="Correlation ID")

    model_config = {
        "json_schema_extra": {
            "example": {
                "session_id": "00000000-0000-0000-0000-000000000001",
                "final_response": "Email sent successfully.",
                "requires_approval": False,
                "interrupted": False,
                "events": [],
            }
        }
    }


class ChatStreamEvent(BaseModel):
    """A single SSE event in a chat stream."""

    event: str = Field(description="Event type identifier")
    data: str = Field(description="JSON-encoded event payload")

    model_config = {
        "json_schema_extra": {
            "example": {
                "event": "tool_call_completed",
                "data": (
                    '{"type":"tool_call_completed","ts":"2026-07-16T12:00:00",'
                    '"payload":{"tool_name":"send_email","status":"success"}}'
                ),
            }
        }
    }


class ChatMessageRequest(BaseModel):
    """Request to send a message in a WebSocket session."""

    type: Literal["message", "ping", "cancel"] = Field(
        description="Message type: message, ping, or cancel"
    )
    content: str | None = Field(default=None, description="Message text content")

    model_config = {
        "json_schema_extra": {
            "example": {
                "type": "message",
                "content": "What's the weather in London?",
            }
        }
    }


class WSSubscriptionEvent(BaseModel):
    """Event emitted to a WebSocket subscriber."""

    type: str = Field(description="Event type")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event data")
    ts: str = Field(description="ISO-8601 timestamp")

    model_config = {
        "json_schema_extra": {
            "example": {
                "type": "plan_created",
                "payload": {"steps": []},
                "ts": "2026-07-16T12:00:00.000000",
            }
        }
    }


# Re-export agent schemas for convenience
from nexus.agent.schemas import (  # noqa: E402, F401
    AgentInvokeRequest,
    AgentInvokeResponse,
    AgentResumeResponse,
    AgentStateResponse,
    AgentStreamEvent,
    ApprovalAction,
)
from nexus.sessions.schemas import (  # noqa: E402, F401
    SessionCreate,
    SessionList,
    SessionRead,
    SessionUpdate,
)
from nexus.tools.schemas import ToolCreate, ToolList, ToolRead, ToolUpdate  # noqa: E402, F401
