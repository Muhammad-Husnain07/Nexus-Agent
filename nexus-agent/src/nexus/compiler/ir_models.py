"""Logical/Physical Intermediate Representation — discriminated union IR for the workflow compiler.

Inspired by LLVM's IR separation: the **Logical** layer represents user intent as
capability-agnostic operations. The **Physical** layer binds those operations to
concrete tools, endpoints, and execution parameters.

All models use ``extra="forbid"`` for strict schema enforcement. Compiler and
Optimizer functions operate on these models purely — no I/O, no datetime, no random.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import Annotated


# ============================================================================
# Logical Layer — User intent as capability-agnostic operations
# ============================================================================


class LogicalNode(BaseModel):
    """A single logical operation in a workflow, emitted by the LLM planner.

    Attributes:
        op: The logical operation name (e.g., ``"get_weather"``, ``"search_books"``).
            Must match ``CapabilityModel.logical_op_name`` in the registry.
        ref: Logical reference label for dependency wiring (e.g., ``"WeatherData"``).
        inputs: Input parameters for the operation.
        depends_on: References of prerequisite nodes that must complete first.
        condition: Optional conditional expression (for branching).
        iterate_over: Optional collection reference to iterate over (for map).
    """

    model_config = ConfigDict(extra="forbid")

    op: str = Field(description="Logical operation name matching CapabilityModel.logical_op_name")
    ref: str = Field(description="Logical reference label for dependency wiring")
    inputs: dict[str, Any] = Field(default_factory=dict, description="Input parameters")
    depends_on: list[str] = Field(default_factory=list, description="Prerequisite node refs")
    condition: str | None = Field(default=None, description="Conditional expression")
    iterate_over: str | None = Field(default=None, description="Collection to iterate over")


class LogicalWorkflow(BaseModel):
    """The complete logical workflow output by the LLM Semantic Planner.

    Contains a sequence of LogicalNodes and any named collections for iteration.
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal["1.0"] = "1.0"
    nodes: list[LogicalNode] = Field(default_factory=list, description="Ordered logical operations")
    collections: dict[str, list[Any]] = Field(
        default_factory=dict,
        description="Named data collections for iteration (e.g., search results)",
    )


# ============================================================================
# Physical Layer — Concrete tool bindings and execution DAG
# ============================================================================


class BasePhysicalNode(BaseModel):
    """Base for all physical execution nodes.

    Attributes:
        id: Globally unique node identifier.
        symbolic_ref: The logical ref this node was compiled from.
        depends_on: IDs of prerequisite physical nodes.
        failure_policy: How failures in this node affect the graph.
        minimum_success: Minimum fraction of sub-tasks that must succeed (0.0–1.0).
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Unique node identifier")
    symbolic_ref: str = Field(description="Logical ref this node was compiled from")
    depends_on: list[str] = Field(default_factory=list, description="Prerequisite node IDs")
    failure_policy: Literal["STOP", "CONTINUE", "BEST_EFFORT"] = Field(
        default="CONTINUE",
        description="How failures propagate",
    )
    minimum_success: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Minimum fraction of sub-tasks that must succeed",
    )

    def compute_execution_key(self, inputs: dict[str, Any], version: str) -> str:
        """Deterministic SHA256 hash for idempotency checking.

        Pure: no I/O, no datetime, no random — same inputs always produce same key.
        """
        payload = json.dumps(
            {"ref": self.symbolic_ref, "inputs": inputs, "version": version},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


class ToolNode(BasePhysicalNode):
    """A concrete tool invocation node — the leaf of the physical DAG.

    Attributes:
        kind: Discriminator for the union type.
        capability: The logical operation name this tool fulfills.
        tool_name: The specific tool/endpoint selected by the optimizer.
        inputs: Resolved input parameters for the HTTP call.
        execution_key: SHA256 hash for idempotency (computed at execution time).
    """

    kind: Literal["tool"] = "tool"
    capability: str = Field(description="Logical operation name")
    tool_name: str = Field(description="Selected tool/endpoint name")
    endpoint_url: str = Field(default="", description="Resolved endpoint URL")
    http_method: str = Field(default="GET", description="HTTP method for the call")
    inputs: dict[str, Any] = Field(default_factory=dict, description="Input parameters")
    cost_estimate: float = Field(default=0.0, description="Estimated cost per call in USD")
    latency_estimate_ms: int = Field(default=1000, description="Estimated P99 latency in ms")
    execution_key: str | None = Field(default=None, description="Idempotency hash")


class MapNode(BasePhysicalNode):
    """A parallel-iteration node — executes its body ToolNode over each item.

    Attributes:
        kind: Discriminator for the union type.
        iterate_over: Reference to the collection to iterate over.
        body: The ToolNode to execute per item.
    """

    kind: Literal["map"] = "map"
    iterate_over: str = Field(description="Collection reference to iterate over")
    body: ToolNode = Field(description="ToolNode to execute per item")


class ReduceNode(BasePhysicalNode):
    """An aggregation node — reduces a collection of results into a single value.

    Attributes:
        kind: Discriminator for the union type.
        aggregate_kind: The type of aggregation to perform.
        source_ref: Reference to the collection to reduce.
        key_path: Dot-separated key for group/filter operations.
        predicate: Filter expression for filter operations.
        limit: Maximum items for top-k operations.
    """

    kind: Literal["reduce"] = "reduce"
    aggregate_kind: Literal["sort", "group_by", "average", "top_k", "filter", "summary"] = Field(
        description="Type of aggregation",
    )
    source_ref: str = Field(description="Collection reference to reduce")
    key_path: str = Field(default="", description="Key path for sort/group/filter")
    predicate: str = Field(default="", description="Filter expression")
    limit: int | None = Field(default=None, description="Max items for top-k")


class ConditionalNode(BasePhysicalNode):
    """A branching node — routes execution based on a condition.

    Attributes:
        kind: Discriminator for the union type.
        source_ref: Reference to the data to evaluate.
        condition: Boolean expression to evaluate.
        branch_true: Node IDs to execute if condition is true.
        branch_false: Node IDs to execute if condition is false.
    """

    kind: Literal["conditional"] = "conditional"
    source_ref: str = Field(description="Data reference to evaluate")
    condition: str = Field(description="Boolean expression")
    branch_true: list[str] = Field(default_factory=list, description="Node IDs if true")
    branch_false: list[str] = Field(default_factory=list, description="Node IDs if false")


# Discriminated union of all physical node types
PhysicalNode = Annotated[
    Union[ToolNode, MapNode, ReduceNode, ConditionalNode],
    Field(discriminator="kind"),
]


class ExecutionGraph(BaseModel):
    """The complete physical execution DAG, produced by the Compiler and refined by the Optimizer.

    Attributes:
        version: Schema version for forward compatibility.
        graph_id: Unique identifier for this graph instance.
        nodes: All physical nodes keyed by ID.
        waves: Pre-computed topological wave ordering for the Executor.
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal["1.0"] = "1.0"
    graph_id: str = Field(description="Unique graph instance identifier")
    nodes: dict[str, PhysicalNode] = Field(
        default_factory=dict,
        description="All physical nodes keyed by ID",
    )
    waves: list[list[str]] = Field(
        default_factory=list,
        description="Pre-computed wave ordering (list of node ID batches)",
    )


# ============================================================================
# Optimization Snapshots — Versioned history of graph transformations
# ============================================================================


class OptimizationReport(BaseModel):
    """Records the transformations applied by a single optimization pass.

    Attributes:
        pass_name: Name of the pass that ran.
        transformations: Human-readable descriptions of each transformation.
        nodes_before: Node count before the pass.
        nodes_after: Node count after the pass.
    """

    model_config = ConfigDict(extra="forbid")

    pass_name: str = Field(description="Optimization pass name")
    transformations: list[str] = Field(default_factory=list, description="Applied transformations")
    nodes_before: int = Field(ge=0, description="Node count before pass")
    nodes_after: int = Field(ge=0, description="Node count after pass")


class GraphSnapshot(BaseModel):
    """A versioned snapshot of the ExecutionGraph during optimization.

    Used for observability, debugging, and rollback.
    """

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=0, description="Snapshot version (monotonic)")
    graph: ExecutionGraph = Field(description="Graph at this snapshot")
    pass_name: str = Field(description="Pass that produced this snapshot")
    report: OptimizationReport | None = Field(default=None, description="Pass report")
