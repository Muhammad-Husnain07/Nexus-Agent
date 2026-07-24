"""Backward-compat re-exports — new code imports from ``state_schema`` directly.

This module re-exports everything from ``state_schema`` and keeps legacy
Pydantic models that older modules (``hitl.py``, dead node files) still
import.  Once all consumers migrate, this file can be removed.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# Re-export everything from the new schema
from nexus.agent.state_schema import (
    AgentState,
    CostTracker,
    EphemeralFlags,
    ExecutionGraph,
    ExecutionNode,
    MessageEntry,
    MessageHistory,
    PersistentContext,
    ToolResult,
    WorkingMemory,
    _EPHEMERAL_FIELDS,
    messages_reducer,
    tool_results_reducer,
)

# ── Legacy models kept for backward compat (old nodes, hitl.py) ──────────


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


RESPONSE_TYPES = Literal["tool", "greeting", "meta", "memory_query"]
"""Supported response type categories."""


class IntentAnalysis(BaseModel):
    """Structured analysis of user intent from the understand_intent node."""
    model_config = {"extra": "ignore"}
    primary_goal: str = Field(description="The user's main objective")
    implied_actions: list[str] = Field(
        default_factory=list, description="Actions implied but not explicitly stated"
    )
    missing_info_slots: list[MissingSlot] = Field(
        default_factory=list, description="Required information not yet provided"
    )
    known_parameters: dict[str, Any] = Field(
        default_factory=dict, description="Parameter values already extracted"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, default=1.0, description="Confidence in this analysis"
    )
    urgency: Literal["low", "normal", "high"] = Field(
        default="normal", description="Perceived urgency"
    )
    needs_tool: bool = Field(default=True, description="Whether this query requires a tool")
    response_type: RESPONSE_TYPES = Field(
        default="tool", description="Category of response"
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


# ── Convenience re-exports for __init__.py ───────────────────────────────
__all__ = [
    "AgentState",
    "AnalysisResult",
    "CostTracker",
    "EphemeralFlags",
    "ExecutionGraph",
    "ExecutionNode",
    "IntentAnalysis",
    "MessageEntry",
    "MessageHistory",
    "MissingSlot",
    "PersistentContext",
    "Plan",
    "PlanStep",
    "RESPONSE_TYPES",
    "ToolResult",
    "WorkingMemory",
    "_EPHEMERAL_FIELDS",
    "messages_reducer",
    "tool_results_reducer",
]
