"""AgentState TypedDict and PlanStep model for the LangGraph orchestration graph."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    """A single step in the agent's execution plan.

    Attributes:
        id: Unique identifier for this step (e.g. ``"step_1"``).
        description: Human-readable description of what this step does.
        tool_name: Name of the tool to invoke, if applicable.
        inputs: Input parameters for the tool call.
        status: Current status of the step.
        depends_on: List of step IDs that must complete before this one.
    """

    id: str = Field(description="Unique step identifier")
    description: str = Field(description="What this step does")
    tool_name: str | None = Field(default=None, description="Tool to invoke")
    inputs: dict[str, Any] | None = Field(default=None, description="Tool input parameters")
    status: Literal["pending", "running", "done", "failed", "skipped"] = Field(
        default="pending", description="Step execution status"
    )
    depends_on: list[str] = Field(default_factory=list, description="Prerequisite step IDs")


class AgentState(TypedDict):
    """State schema for the LangGraph orchestration graph.

    All fields use plain dict types so the state is easily serialised for
    checkpointing.  Messages use the ``add_messages`` reducer.
    """

    messages: list[dict[str, Any]]
    tenant_id: str
    session_id: str
    user_id: str
    plan: list[dict[str, Any]] | None
    current_step_index: int
    gathered_requirements: dict[str, Any]
    available_tools: list[dict[str, Any]]
    pending_approval: dict[str, Any] | None
    iteration_count: int
    scratchpad: str
    tool_results: list[dict[str, Any]]
    final_response: str | None
    intent: dict[str, Any] | None
    missing_info_slots: list[str] | None
    errors: list[str]
    _bound_tools: list[dict[str, Any]]
