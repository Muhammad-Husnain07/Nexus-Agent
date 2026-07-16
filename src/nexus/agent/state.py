"""AgentState TypedDict and Pydantic models for the LangGraph orchestration graph."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    """A single step in the agent's execution plan."""

    id: str = Field(description="Unique step identifier")
    description: str = Field(description="What this step does")
    tool_name: str | None = Field(default=None, description="Tool to invoke")
    inputs: dict[str, Any] | None = Field(default=None, description="Tool input parameters")
    status: Literal["pending", "running", "done", "failed", "skipped"] = Field(
        default="pending", description="Step execution status"
    )
    depends_on: list[str] = Field(default_factory=list, description="Prerequisite step IDs")
    expected_outcome: str | None = Field(
        default=None, description="What successful execution should produce"
    )
    is_destructive: bool = Field(
        default=False, description="Whether this step modifies/deletes data"
    )


class Plan(BaseModel):
    """Full plan produced by the plan node."""

    rationale: str = Field(description="Explanation of the plan strategy")
    estimated_tool_calls: int = Field(ge=0, default=0, description="Expected number of tool calls")
    reversible: bool = Field(default=True, description="Whether the plan can be reversed")
    steps: list[PlanStep] = Field(description="Ordered list of steps")
    needs_human_review: bool = Field(
        default=False, description="Flagged for human review if destructive or requires_approval"
    )


class MissingSlot(BaseModel):
    """A piece of information required to proceed, identified during intent analysis."""

    name: str = Field(description="Short identifier for the missing slot")
    description: str = Field(description="What this information is")
    why_needed: str = Field(description="Why this is required")
    suggested_question: str = Field(description="How to ask the user for this")
    possible_values: list[str] | None = Field(
        default=None, description="Predefined options if applicable"
    )
    source: Literal["user", "tool", "context"] = Field(
        default="user", description="Where this info should come from"
    )


class IntentAnalysis(BaseModel):
    """Structured analysis of user intent from the understand_intent node."""

    primary_goal: str = Field(description="The user's main objective")
    implied_actions: list[str] = Field(
        default_factory=list, description="Actions implied but not explicitly stated"
    )
    missing_info_slots: list[MissingSlot] = Field(
        default_factory=list, description="Required information not yet provided"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, default=1.0, description="Confidence in this analysis"
    )
    urgency: Literal["low", "normal", "high"] = Field(
        default="normal", description="Perceived urgency"
    )


class AnalysisResult(BaseModel):
    """Decision from the analyze_results node after reviewing a step outcome."""

    outcome: Literal["success", "partial", "failure"] = Field(
        description="How well the step result matched expectations"
    )
    next_action: Literal["continue", "revise", "clarify", "finalize", "escalate"] = Field(
        description="What to do next"
    )
    reasoning: str = Field(default="", description="Explanation of this decision")


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
    intent_analysis: dict[str, Any] | None
    analysis_result: dict[str, Any] | None
    needs_human_review: bool
    questions_asked: int
    _routing_decision: str
