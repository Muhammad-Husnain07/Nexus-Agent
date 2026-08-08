"""Typed event models (Phase 7) — one model per emitted event type.

The runtime's observability boundary: every ``AgentEvent`` payload is a typed,
frozen model instead of an implicit dict. Rich fields (cost, latency,
retries, decision reasons) make every node answer *why* + *what* + *cost*.
Serialization stays JSON-compatible via ``model_dump``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from nexus.execution.lifecycle import ExecutionStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BaseEvent(BaseModel):
    """Shared event envelope fields."""

    model_config = ConfigDict(frozen=True)

    type: str = Field(description="Event type (stable identifier)")
    ts: str = Field(default_factory=_now, description="Emit timestamp (ISO-8601 UTC)")
    payload: dict[str, Any] = Field(default_factory=dict, description="Typed payload (model_dump)")


class NodeCompletedEvent(BaseModel):
    """Emitted when a graph node finishes."""

    model_config = ConfigDict(frozen=True)

    node: str = Field(description="Node name")
    duration_ms: float = Field(default=0.0, description="Node wall time")
    has_output: bool = Field(default=False, description="Whether the node produced updates")
    cost_usd: float = Field(default=0.0, description="Node-attributed cost (LLM/tools)")
    retries: int = Field(default=0, description="Retry count inside the node")


class ToolCallEvent(BaseModel):
    """Emitted per tool execution."""

    model_config = ConfigDict(frozen=True)

    tool_name: str = Field(description="Tool invoked")
    status: str = Field(description="success | error | validation_error | timeout | rate_limited")
    data: Any = Field(default=None, description="Tool output (normalized)")
    error: str | None = Field(default=None, description="Failure reason")
    task_id: str = Field(default="", description="Execution task id")
    duration_ms: float = Field(default=0.0, description="Execution wall time")
    retries: int = Field(default=0, description="Retry count")
    cached: bool = Field(default=False, description="Served from long-term artifact cache")
    cost_usd: float = Field(default=0.0, description="Attributed cost")


class PlanCreatedEvent(BaseModel):
    """Emitted when the compiler produces the execution graph."""

    model_config = ConfigDict(frozen=True)

    steps: dict[str, str] = Field(default_factory=dict, description="task_id → tool_name")
    waves: int = Field(default=0, description="Number of execution waves")
    strategy: str = Field(default="", description="Selected execution strategy (Phase 4)")
    estimated_cost_usd: float = Field(default=0.0, description="Estimated cost")
    estimated_latency_ms: int = Field(default=0, description="Estimated latency")


class ErrorEvent(BaseModel):
    """Emitted on any failure."""

    model_config = ConfigDict(frozen=True)

    message: str = Field(description="Human-readable error")
    code: str = Field(default="", description="Stable error code when known")
    tool_name: str | None = Field(default=None, description="Tool involved (tool errors)")


class DecisionEvent(BaseModel):
    """Emitted by routing/classification — answers WHY."""

    model_config = ConfigDict(frozen=True)

    decision: str = Field(description="What was decided (route / goal / strategy)")
    reason: str = Field(default="", description="Why (deterministic or classifier output)")
    candidates: list[str] = Field(default_factory=list, description="Considered candidates")


class FinalResponseEvent(BaseModel):
    """Emitted when the final response is composed."""

    model_config = ConfigDict(frozen=True)

    text: str = Field(default="", description="Final response text")
    cost_usd: float = Field(default=0.0, description="Total turn cost")
    latency_ms: float = Field(default=0.0, description="Total turn latency")


class NodeStartedEvent(BaseModel):
    """Emitted when a graph node starts."""

    model_config = ConfigDict(frozen=True)

    node: str = Field(description="Node name")
    ts: str = Field(default_factory=_now, description="Start timestamp")


class NodeFailedEvent(BaseModel):
    """Emitted when a graph node fails."""

    model_config = ConfigDict(frozen=True)

    node: str = Field(description="Node name")
    error: str = Field(default="", description="Failure reason")


class ApprovalRequestedEvent(BaseModel):
    """Emitted when a conversational approval checkpoint pauses the run."""

    model_config = ConfigDict(frozen=True)

    pending_tools: list[str] = Field(default_factory=list, description="Tools awaiting approval")
    message: str = Field(default="", description="Human-readable approval question")


class StepProgressEvent(BaseModel):
    """The stable UI contract — human-readable step progression.

    Status ladder: QUEUED → RUNNING → WAITING | APPROVAL | RETRYING →
    COMPLETED | FAILED | CANCELLED | SKIPPED. The frontend renders ONLY this
    event; all other ExecutionEvent types feed telemetry/audit/history.
    """

    model_config = ConfigDict(frozen=True)

    step: str = Field(description="Stable step id (task id / step ref)")
    status: ExecutionStatus = Field(description="Ladder position (see ExecutionStatus)")
    text: str = Field(default="", description="Human-readable progress line")
    tool_name: str = Field(default="", description="Tool involved (when applicable)")


class ExecutionCompletedEvent(BaseModel):
    """Emitted when the whole execution finishes."""

    model_config = ConfigDict(frozen=True)

    status: ExecutionStatus = Field(description="Final execution status")
    final_response: str = Field(default="", description="Composed response")
    cost_usd: float = Field(default=0.0, description="Total cost")
    duration_ms: float = Field(default=0.0, description="Total wall time")


class ExecutionEvent(BaseModel):
    """Immutable, append-only per-task execution event (in-state audit trail).

    Unlike the SSE stream (transient), ``_execution_events`` persists a
    bounded replayable log of every task lifecycle transition in the turn's
    state: STARTED / COMPLETED / FAILED / RETRY / CACHED / SKIPPED. It is
    the foundation for debugging, replay, and the artifact cache (events
    reference artifact/execution ids).
    """

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(description="Stable unique event id (uuid4)")
    timestamp: str = Field(description="ISO-8601 UTC timestamp")
    type: str = Field(description="TASK_STARTED | TASK_COMPLETED | TASK_FAILED | TASK_RETRY | TASK_CACHED | TASK_SKIPPED | GRAPH_COMPLETED")
    execution_id: str = Field(default="", description="Execution/task id")
    tool_name: str = Field(default="", description="Tool involved")
    artifact_id: str = Field(default="", description="Artifact id (when produced)")
    status: str = Field(default="", description="Outcome status when applicable")
    duration_ms: float = Field(default=0.0, description="Task duration")
    error: str = Field(default="", description="Error text when failed")


_EVENT_MODEL_MAP: dict[str, type[BaseModel]] = {
    "node_started": NodeStartedEvent,
    "node_completed": NodeCompletedEvent,
    "node_failed": NodeFailedEvent,
    "tool_call_completed": ToolCallEvent,
    "plan_created": PlanCreatedEvent,
    "error": ErrorEvent,
    "routing_decision": DecisionEvent,
    "final_response": FinalResponseEvent,
    "approval_checkpoint": ApprovalRequestedEvent,
    "step_progress": StepProgressEvent,
    "execution_completed": ExecutionCompletedEvent,
}


def build_event(type_: str, payload: dict[str, Any]) -> BaseEvent:
    """Validate a payload against its typed model (no-op passthrough when
    the event type has no dedicated model yet)."""
    model = _EVENT_MODEL_MAP.get(type_)
    if model is None:
        return BaseEvent(type=type_, payload=payload)
    try:
        typed = model(**payload)
        return BaseEvent(type=type_, payload=typed.model_dump())
    except Exception:
        return BaseEvent(type=type_, payload=payload)
