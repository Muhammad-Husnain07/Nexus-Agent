"""Intent model — structured output from query classification.

Extends the router's QueryType with richer metadata: extracted entities,
constraints, confidence, and missing-information slots.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SlotSpec(BaseModel):
    """A piece of missing information that the RequirementCollector can ask about."""

    name: str = Field(description="Slot name (e.g. 'date', 'location')")
    question: str = Field(description="Natural question to ask the user")
    options: list[str] | None = Field(default=None, description="Suggested options")
    required: bool = Field(default=True, description="Whether this slot is mandatory")


class Intent(BaseModel):
    """Structured intent extracted from a user query.

    Produced by the RouterNode during classification and consumed by
    the RequirementCollectorNode and SemanticPlannerNode.
    All fields populated via LLM + heuristic fallback.
    """

    query_type: Literal[
        "single_tool", "independent_multi", "dependent_multi",
        "conversational", "no_tool", "knowledge_only", "needs_requirements",
        "workflow",
        "conversation", "information", "analysis", "action",
    ] = Field(description="Query type for graph routing")

    entities: dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted entities (e.g. {'city': 'Tokyo', 'date': '2024-01-15'})",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="User-specified constraints (e.g. ['budget < $0.10'])",
    )
    missing_info: list[SlotSpec] = Field(
        default_factory=list,
        description="Information gaps that need user input before planning",
    )
    confidence: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="Classification confidence (0.0–1.0)",
    )
    suggested_capability: str | None = Field(
        default=None,
        description="Primary capability name suggested by the router",
    )
