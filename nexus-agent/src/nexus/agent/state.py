"""AgentState TypedDict and Pydantic models for the LangGraph orchestration graph."""

from __future__ import annotations

import uuid
from operator import add
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field


def _any_true(a: bool, b: bool) -> bool:
    return a or b


def milestone_reducer(
    current: list[dict[str, Any]],
    update: list[dict[str, Any]] | dict[str, Any],
) -> list[dict[str, Any]]:
    """Rolling window reducer — keeps last 10 messages + milestone-tagged ones.

    Replaces ``add_messages`` to prevent O(N²) context growth.  Critical
    messages (system prompt, first user query, tool results) are tagged
    with ``_milestone=True`` and survive the window.

    Deduplicates by message ID (like LangGraph's ``add_messages``):
    if a message has the same ID as an existing one, the later replaces
    the earlier.  Messages without an ID get a UUID assigned.
    """
    full = (current or []) + (update if isinstance(update, list) else [update])

    # Assign stable IDs to messages missing them
    for m in full:
        if isinstance(m, dict):
            m.setdefault("id", str(uuid.uuid4()))

    # Dedup by ID — later message replaces earlier one with same ID
    seen: dict[str, int] = {}
    deduped: list[dict[str, Any]] = []
    for m in full:
        if isinstance(m, dict):
            mid = m.get("id")
            if mid and mid in seen:
                deduped[seen[mid]] = m  # replace
                continue
            if mid:
                seen[mid] = len(deduped)
        deduped.append(m)

    # Rolling window: keep last 10 + milestone-tagged
    cutoff = max(0, len(deduped) - 10)
    kept: list[dict[str, Any]] = []
    for i, msg in enumerate(deduped):
        if i >= cutoff or isinstance(msg, dict) and msg.get("_milestone"):
            kept.append(msg)
    return kept


def _merge_results(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Merge two dag_results dicts. Right takes precedence for overlapping keys."""
    merged = dict(left)
    merged.update(right)
    return merged


def _merge_reflection_history(
    left: list[dict[str, Any]], right: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Accumulate reflection history entries across rounds."""
    return left + right


def _dag_tasks_reducer(
    current: list[dict[str, Any]],
    update: list[dict[str, Any]] | dict[str, Any],
) -> list[dict[str, Any]]:
    """Merge dag_tasks updates from parallel tool executions.
    
    When tool_executor returns via Send(), it returns a single-item list
    with {id, status: "done"}. This reducer updates the existing task's
    status without replacing the entire list.
    
    Args:
        current: The existing dag_tasks list from state
        update: Either a single task dict or list of task dicts to merge
        
    Returns:
        Merged dag_tasks list with updated statuses
    """
    if not current:
        return update if isinstance(update, list) else [update]
    
    if not update:
        return current
    
    # Normalize update to list
    updates = update if isinstance(update, list) else [update]
    
    # Create a map of updates by id
    update_map = {t["id"]: t for t in updates if isinstance(t, dict) and "id" in t}
    
    # Merge: update existing tasks, keep unchanged ones
    result = []
    for task in current:
        if isinstance(task, dict) and task.get("id") in update_map:
            # Merge the update into the existing task
            merged = {**task, **update_map[task["id"]]}
            result.append(merged)
        else:
            result.append(task)
    
    return result


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


# Fields that are cleared between turns — not persisted across checkpoints
_EPHEMERAL_FIELDS: list[str] = [
    "_routing_decision",
    "_tool_executed_in_turn",
    "_safety_result",
    "_plan_valid",
    "_plan_validation_failures",
    "_invalid_results",
    "_plan_repair_count",
    "_tool_retry_count",
    "dag_tasks",
    "dag_results",
    "dag_phase",
    "dag_iteration",
    "tool_results",
    "tool_results_ref",
    "errors",
    "pending_approval",
    "_active_speculations",
    "_pending_splits",
    "_dag_generation",
    "_split_tools",
]

RESPONSE_TYPES = Literal["tool", "greeting", "meta", "memory_query"]
"""Supported response type categories — a query either needs a tool or can be
answered directly via greeting / meta / memory-query."""


class IntentAnalysis(BaseModel):
    """Structured analysis of user intent from the understand_intent node."""

    model_config = {"extra": "ignore"}  # tolerate extra fields from LLM

    primary_goal: str = Field(description="The user's main objective")
    implied_actions: list[str] = Field(
        default_factory=list, description="Actions implied but not explicitly stated"
    )
    missing_info_slots: list[MissingSlot] = Field(
        default_factory=list, description="Required information not yet provided"
    )
    known_parameters: dict[str, Any] = Field(
        default_factory=dict, description="Parameter values already extracted from the user's message"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, default=1.0, description="Confidence in this analysis"
    )
    urgency: Literal["low", "normal", "high"] = Field(
        default="normal", description="Perceived urgency"
    )
    needs_tool: bool = Field(
        default=True,
        description="Whether this query requires a tool invocation",
    )
    response_type: RESPONSE_TYPES = Field(
        default="tool",
        description="Category of response: tool, greeting, meta, or memory_query",
    )


class AnalysisResult(BaseModel):
    """Decision from the analyze_results node after reviewing a step outcome."""

    outcome: Literal["success", "partial", "failure"] = Field(
        description="How well the step result matched expectations"
    )
    next_action: Literal["continue", "revise", "clarify", "finalize", "escalate", "preview"] = Field(
        description="What to do next"
    )
    reasoning: str = Field(default="", description="Explanation of this decision")


class AgentState(TypedDict):
    """State schema for the LangGraph orchestration graph.

    All fields use plain dict types so the state is easily serialised for
    checkpointing.  Messages use the ``add_messages`` reducer.
    """

    messages: Annotated[list[dict[str, Any]], milestone_reducer]
    session_id: str
    user_context: dict[str, Any]
    plan: list[dict[str, Any]] | None
    current_step_index: int
    gathered_requirements: dict[str, Any]
    available_tools: list[dict[str, Any]]
    pending_approval: dict[str, Any] | None
    iteration_count: int
    scratchpad: str
    tool_results: Annotated[list[dict[str, Any]], add]
    final_response: str | None
    intent: dict[str, Any] | None
    missing_info_slots: list[str] | None
    errors: list[str]
    _bound_tools: list[dict[str, Any]]
    intent_analysis: dict[str, Any] | None
    analysis_result: dict[str, Any] | None
    needs_human_review: bool
    questions_asked: int
    response_type: str
    reflection_score: float
    reflection_feedback: str
    reflection_count: int
    working_memory: dict[str, Any]
    reflection_history: Annotated[list[dict[str, Any]], _merge_reflection_history]
    task_difficulty: float | None
    total_cost_usd: float
    _cost_breakdown: dict[str, Any]
    _total_tokens: int
    _prompt_versions: dict[str, str]
    self_consistency_samples: list[dict[str, Any]] | None
    calibration_data: dict[str, Any]
    _max_concurrent_tasks: int | None
    _active_speculations: dict[str, Any] | None
    _pending_splits: list[str]
    _dag_generation: int
    dag_tasks: Annotated[list[dict[str, Any]], _dag_tasks_reducer]
    dag_results: Annotated[dict[str, Any], _merge_results]
    dag_phase: str
    _routing_decision: str
    _tool_executed_in_turn: Annotated[bool, _any_true]
    _safety_result: dict[str, Any]
    _plan_valid: bool
    _plan_validation_failures: list[dict[str, Any]]
    _invalid_results: list[dict[str, Any]]
    dag_iteration: int
    max_dag_iterations: int
    reflection_revisions: int
    max_reflection_revisions: int
    is_high_risk: bool
    _plan_repair_count: int
    _tool_retry_count: int
    _split_tools: list[str]
    tool_results_ref: str
    _ephemeral_keys: list[str]
