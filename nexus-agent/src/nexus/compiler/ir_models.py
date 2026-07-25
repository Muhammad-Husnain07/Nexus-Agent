"""4-layer Intermediate Representation stack — Intent → Goal → Operation → Execution.

Inspired by LLVM's IR: each layer is a typed, validated transformation of the
previous. No magic strings. No mutable state. All models use ``extra="forbid"``
for strict schema enforcement.

Layers:
1. **IntentIR** — User's raw semantic intent extracted from natural language.
2. **GoalIR** — Atomic steps required to satisfy the intent (derived from GoalTemplates).
3. **OperationIR** — Capability-bound operations with resolved parameters.
4. **ExecutionIR** — The final compiled DAG node with tool binding, control flow, and retry policy.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


# ============================================================================
# Layer 1: IntentIR — Raw semantic intent from NL
# ============================================================================


class IntentIR(BaseModel):
    """User's raw semantic intent, extracted from natural language.

    Attributes:
        action: The action verb (e.g., "retrieve", "compare", "create", "delete").
        domain: The domain/ subject area (e.g., "weather", "crypto", "bookmark").
        entities: Key-value parameters extracted from the query.
        confidence: Extraction confidence (0.0–1.0).
        raw_query: Original user query for traceability.
    """

    action: str = Field(description="Action verb (retrieve, compare, create, delete, etc.)")
    domain: str = Field(default="general", description="Subject domain (weather, crypto, bookmark, etc.)")
    entities: dict[str, Any] = Field(default_factory=dict, description="Extracted parameters")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Extraction confidence")
    raw_query: str = Field(default="", description="Original user query")

    model_config = {"extra": "forbid"}


# ============================================================================
# Layer 2: GoalIR — Atomic step derived from GoalTemplate
# ============================================================================


class GoalIR(BaseModel):
    """An atomic step required to satisfy an intent.

    Derived from GoalTemplate expansion. Each goal maps to one or more
    capabilities that can fulfill it.

    Attributes:
        id: Unique goal identifier.
        action: The action this goal represents.
        domain: The domain this goal operates in.
        required_artifacts: Artifact field names needed as input.
        produced_artifacts: Artifact field names produced as output.
        confidence: How well this goal satisfies the original intent.
    """

    id: str = Field(default_factory=lambda: f"goal_{uuid.uuid4().hex[:8]}")
    action: str = Field(description="Action verb")
    domain: str = Field(default="general", description="Subject domain")
    required_artifacts: list[str] = Field(default_factory=list, description="Input artifacts needed")
    produced_artifacts: list[str] = Field(default_factory=list, description="Output artifacts produced")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    model_config = {"extra": "forbid"}


# ============================================================================
# Layer 3: OperationIR — Capability-bound resolved operation
# ============================================================================


class OperationIR(BaseModel):
    """A capability-bound operation with resolved parameters.

    Attributes:
        id: Unique operation identifier.
        capability_name: The capability fulfilling this operation.
        tool_name: The specific tool selected (by Optimizer).
        inputs: Resolved input parameters.
        expected_outputs: Expected output artifact field names.
        depends_on: IDs of operations that must complete first.
        retry_policy: Strategy for handling failures (from Provider Contract).
        cost_estimate: Estimated cost of this operation.
    """

    id: str = Field(default_factory=lambda: f"op_{uuid.uuid4().hex[:8]}")
    capability_name: str = Field(description="Capability fulfilling this operation")
    tool_name: str = Field(default="", description="Specific tool selected")
    inputs: dict[str, Any] = Field(default_factory=dict, description="Resolved input parameters")
    expected_outputs: list[str] = Field(default_factory=list, description="Expected output artifacts")
    depends_on: list[str] = Field(default_factory=list, description="Prerequisite operation IDs")
    retry_policy: str = Field(default="default", description="Retry strategy name")
    cost_estimate: float = Field(default=0.0, ge=0.0, description="Estimated cost in USD")

    model_config = {"extra": "forbid"}


# ============================================================================
# Layer 4: ExecutionIR — Compiled DAG node
# ============================================================================


class ExecutionControlFlow(str, Enum):
    """Control flow type for an execution node."""
    CALL = "call"
    CONDITIONAL = "conditional"
    FOR_EACH = "for_each"
    GUARD = "guard"


class ExecutionIR(BaseModel):
    """A single node in the final compiled execution DAG.

    Attributes:
        id: Unique execution node identifier.
        kind: Control flow type (call, conditional, for_each, guard).
        tool_name: The resolved tool to call (for CALL nodes).
        inputs: Resolved input parameters.
        depends_on: IDs of prerequisite execution nodes.
        condition: Conditional expression (for CONDITIONAL nodes).
        iterate_over: Iteration source (for FOR_EACH nodes).
        empty_fallback: Fallback when iteration source is empty.
        timeout_s: Per-call timeout in seconds.
        max_retries: Maximum retry attempts.
    """

    id: str = Field(default_factory=lambda: f"exec_{uuid.uuid4().hex[:8]}")
    kind: ExecutionControlFlow = Field(default=ExecutionControlFlow.CALL, description="Control flow type")
    tool_name: str = Field(default="", description="Tool to call")
    inputs: dict[str, Any] = Field(default_factory=dict, description="Input parameters")
    depends_on: list[str] = Field(default_factory=list, description="Prerequisite node IDs")
    condition: str = Field(default="", description="Conditional expression")
    iterate_over: str = Field(default="", description="Iteration source field")
    empty_fallback: dict[str, Any] = Field(default_factory=dict, description="Fallback when empty")
    timeout_s: float = Field(default=30.0, ge=1.0, description="Per-call timeout")
    max_retries: int = Field(default=2, ge=0, description="Max retry attempts")

    model_config = {"extra": "forbid"}


# ============================================================================
# IRStack — The full stack for one turn
# ============================================================================


class IRStack(BaseModel):
    """Tracks the IR transformation pipeline for one turn.

    Each turn produces: IntentIR → GoalIR[] → OperationIR[] → ExecutionIR[].
    The stack preserves all layers for observability and incremental re-compilation.

    Attributes:
        intents: Extracted semantic intents (Layer 1).
        goals: Expanded atomic goals (Layer 2).
        operations: Resolved capability operations (Layer 3).
        execution_plan: Compiled execution DAG nodes (Layer 4).
        version: Incrementing version — each re-compilation bumps this.
    """

    intents: list[IntentIR] = Field(default_factory=list, description="Layer 1: Semantic intents")
    goals: list[GoalIR] = Field(default_factory=list, description="Layer 2: Atomic goals")
    operations: list[OperationIR] = Field(default_factory=list, description="Layer 3: Resolved operations")
    execution_plan: list[ExecutionIR] = Field(default_factory=list, description="Layer 4: Compiled DAG")
    version: int = Field(default=0, description="Stack version — incremented on re-compilation")

    model_config = {"extra": "forbid"}

    def add_intent(self, intent: IntentIR) -> IRStack:
        return self.model_copy(update={"intents": self.intents + [intent]})

    def add_goal(self, goal: GoalIR) -> IRStack:
        return self.model_copy(update={"goals": self.goals + [goal]})

    def add_operation(self, op: OperationIR) -> IRStack:
        return self.model_copy(update={"operations": self.operations + [op]})

    def set_execution_plan(self, nodes: list[ExecutionIR]) -> IRStack:
        return self.model_copy(update={"execution_plan": nodes, "version": self.version + 1})

    def clear_turn(self) -> IRStack:
        return IRStack(version=self.version + 1)
