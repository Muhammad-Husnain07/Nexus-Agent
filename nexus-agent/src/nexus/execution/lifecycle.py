"""Execution lifecycle contracts — ExecutionRequest → ExecutionPlan → ExecutionResult.

Three immutable contracts cover the complete execution lifecycle:

- ``ExecutionRequest`` — the replayable, traceable identity of an execution
  (immutable metadata: versions, session, message).
- ``ExecutionStatus`` — the shared status ladder used by StepProgress events
  and ExecutionResult (QUEUED → RUNNING → … → COMPLETED/FAILED).
- ``ExecutionResult`` — the typed outcome of a background execution.

Version fields are wired from immutable module-level constants (implementation
versions, never settings/env — see ``RESOLVER_VERSION``, ``PLANNER_VERSION``,
``COMPILER_VERSION``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExecutionStatus(str, Enum):
    """Shared status ladder for steps and whole executions."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    APPROVAL = "approval"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExecutionRequest(BaseModel):
    """Immutable execution identity — replayable, fully traceable."""

    model_config = ConfigDict(frozen=True)

    execution_id: str = Field(description="Execution identity (uuid) — replay/trace key")
    session_id: str = Field(description="Owning conversation session")
    thread_id: str | None = Field(default=None, description="Checkpointer thread (session-aligned)")
    message: str = Field(description="User message that triggered the execution")
    execution_plan_version: int = Field(description="Execution-plan IR version")
    resolver_version: int = Field(description="ResolutionEngine implementation version")
    planner_version: int = Field(description="Logical-planner implementation version")
    compiler_version: int = Field(description="Compiler/codegen implementation version")
    registry_version: int = Field(default=0, description="Registry version at request time")
    created_at: str = Field(default_factory=_utc_now, description="Request creation time")


class ExecutionResult(BaseModel):
    """Typed outcome of an execution (background worker writes this)."""

    model_config = ConfigDict(frozen=True)

    execution_id: str = Field(description="Matches the ExecutionRequest id")
    status: ExecutionStatus = Field(description="Final execution status")
    final_response: str = Field(default="", description="Composed final response")
    produced_artifacts: list[str] = Field(
        default_factory=list, description="Artifact ids/names produced"
    )
    events: list[dict[str, Any]] = Field(
        default_factory=list, description="Validated ExecutionEvent stream (type + payload)"
    )
    progress_lines: list[str] = Field(
        default_factory=list, description="Human-readable progress timeline"
    )
    started_at: str = Field(default_factory=_utc_now, description="Execution start")
    completed_at: str = Field(default_factory=_utc_now, description="Execution completion")
    duration_ms: int = Field(default=0, description="Total wall time")
