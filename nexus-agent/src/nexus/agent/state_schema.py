"""Production-grade AgentState schema — tiered memory, type-safe, reducer-optimized.

Lifecycle Architecture
======================

The state is split into three tiers based on lifespan:

                    ┌──────────────────────────────────────────────┐
                    │         Persistent Context                  │
                    │  (survives across conversation turns)       │
                    │  session_id, user_context, approved_tools   │
                    │  Checkpointed ALWAYS.  Rarely changes.      │
                    └──────────────────────────────────────────────┘
                                      │
                    ┌──────────────────────────────────────────────┐
                    │           Working Memory                     │
                    │  (cleared after task/subtask batch)         │
                    │  messages, current_plan, tool_results       │
                    │  Checkpointed per-turn.  Changes frequently. │
                    └──────────────────────────────────────────────┘
                                      │
                    ┌──────────────────────────────────────────────┐
                    │          Ephemeral Flags                     │
                    │  (cleared every node execution)              │
                    │  routing decisions, retry counts, safety     │
                    │  NOT checkpointed across node boundaries.    │
                    └──────────────────────────────────────────────┘

Migration from existing ``state.py``:
- Phase A: Add this file alongside ``state.py`` (no breaking changes)
- Phase B: Update ``AgentRunner`` to populate the new structure
- Phase C: Migrate nodes one at a time
- Phase D: Remove old ``state.py`` fields
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


# ============================================================================
# Pydantic Models (type-safe nested objects)
# ============================================================================


class ToolResult(BaseModel):
    """A single tool execution result with metadata for observability.

    Replaces the raw dict pattern in the current ``tool_results`` list.
    Each result carries its own timing, cost, and DAG generation info
    so downstream nodes (finalize, reflection) can make informed decisions.
    """

    tool_name: str
    status: Literal["success", "error", "timeout", "validation_error"]
    data: Any = None
    error: str | None = None
    task_id: str = ""
    duration_ms: float = 0.0
    cost_usd: float = 0.0
    dag_generation: int = 0


class ExecutionNode(BaseModel):
    """A node in the execution DAG (the task graph, not LangGraph's own graph).

    Each node represents one tool call (or speculative approach batch).
    Dependencies are expressed as a list of node IDs that must complete first.

    Lifecycle:
        1. ``pending`` — created by planner, waiting for dependencies
        2. ``running`` — sent to ``tool_executor`` via ``Send()``
        3. ``completed`` — result received and validated
        4. ``failed`` — max retries exceeded or unrecoverable error
        5. ``skipped`` — dependency failed, no point executing
    """

    id: str = Field(description="Unique task identifier (e.g. task_1, task_3_sub_0)")
    tool_name: str | None = Field(default=None, description="Tool to invoke")
    description: str = Field(default="", description="Human-readable description")
    inputs: dict[str, Any] = Field(default_factory=dict, description="Tool input parameters")
    depends_on: list[str] = Field(default_factory=list, description="Prerequisite node IDs")
    status: Literal["pending", "running", "completed", "failed", "skipped"] = "pending"
    result: ToolResult | None = Field(default=None, description="Execution result when done")
    retry_count: int = Field(default=0, ge=0, description="Number of retries so far")
    max_retries: int = Field(default=2, ge=0, description="Max retries before giving up")


class ExecutionGraph(BaseModel):
    """Full DAG structure for observability and routing.

    Replaces the separate ``dag_tasks``, ``dag_results``, ``completed_task_ids``,
    ``_pending_splits``, ``_split_tools``, and ``_dag_generation`` fields from
    the current state.  Everything the DAG executor needs lives here.

    Usage::

        graph = ExecutionGraph()
        graph.add_node(ExecutionNode(id="task_1", tool_name="get_geocoding"))
        graph.add_node(ExecutionNode(
            id="task_2", tool_name="get_weather",
            depends_on=["task_1"],
        ))
        for node in graph.ready_nodes():
            send(node)
    """

    nodes: dict[str, ExecutionNode] = Field(
        default_factory=dict,
        description="All nodes keyed by ID",
    )
    generation: int = Field(
        default=0,
        description="DAG expansion generation (dag_splitter counter)",
    )
    concurrent_budget: int = Field(
        default=5,
        description="Max parallel executions",
    )
    split_tools: list[str] = Field(
        default_factory=list,
        description="Tools that have already been split (recursion guard)",
    )

    def add_node(self, node: ExecutionNode) -> None:
        """Add a single node to the graph."""
        self.nodes[node.id] = node

    def add_nodes(self, nodes: list[ExecutionNode]) -> None:
        """Add multiple nodes at once."""
        for n in nodes:
            self.nodes[n.id] = n

    def ready_nodes(self) -> list[ExecutionNode]:
        """Return nodes whose dependencies are satisfied."""
        return [
            n for n in self.nodes.values()
            if n.status == "pending"
            and all(
                self.nodes.get(d) and self.nodes[d].status == "completed"
                for d in n.depends_on
            )
        ]

    def remaining(self) -> list[ExecutionNode]:
        """Return nodes not yet completed or failed (still actionable)."""
        return [
            n for n in self.nodes.values()
            if n.status in ("pending", "running")
        ]

    def failed(self) -> list[str]:
        """Return IDs of nodes that have exceeded their retry budget."""
        return [
            n.id for n in self.nodes.values()
            if n.status == "failed"
        ]

    def update_result(self, task_id: str, result: ToolResult) -> None:
        """Record a tool result and update node status."""
        node = self.nodes.get(task_id)
        if node is None:
            return
        node.result = result
        if result.status == "success":
            node.status = "completed"
        elif result.status in ("error", "timeout", "validation_error"):
            node.retry_count += 1
            if node.retry_count >= node.max_retries:
                node.status = "failed"
            else:
                node.status = "pending"  # will be retried

    def mark_skipped(self, task_id: str) -> None:
        """Mark a node as skipped (dependency failed)."""
        node = self.nodes.get(task_id)
        if node:
            node.status = "skipped"


class CostTracker(BaseModel):
    """Token and cost accumulator with per-node breakdown.

    Separated from the main state so cost tracking doesn't pollute
    routing logic.  Updated by ``tool_executor`` and read by
    ``finalize`` and ``reflect_on_response`` (cost budget check).
    """

    total_cost_usd: float = 0.0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    per_node: dict[str, float] = Field(
        default_factory=dict,
        description="node_name → accumulated cost",
    )

    def record(self, node_name: str, cost_usd: float = 0.0, tokens: int = 0, inp: int = 0, out: int = 0) -> None:
        """Record cost and token usage for a node."""
        self.total_cost_usd += cost_usd
        self.total_tokens += tokens
        self.input_tokens += inp
        self.output_tokens += out
        self.per_node[node_name] = self.per_node.get(node_name, 0.0) + cost_usd

    def budget_remaining(self, budget: float) -> float:
        """Return remaining budget (budget minus total_cost_usd)."""
        return max(0.0, budget - self.total_cost_usd)


class MessageEntry(BaseModel):
    """A single message with metadata for efficient truncation and dedup.

    Replaces the raw dict pattern in ``messages``.  The ``milestone``
    flag tells the reducer to NEVER truncate this entry (survives the
    rolling window).  The ``id`` field is used for dedup — if the same
    ``id`` appears in an update, the old entry is replaced (not appended).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique message identifier")
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    milestone: bool = Field(default=False, description="Never truncated by rolling window")
    created_at: float = Field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp(),
        description="Unix timestamp of creation",
    )


# ============================================================================
# Reducers
# ============================================================================


def messages_reducer(
    current: list[MessageEntry] | None,
    update: list[MessageEntry] | MessageEntry | None,
) -> list[MessageEntry]:
    """Rolling-window message reducer with ID dedup and milestone protection.

    Lifecycle
    ---------
    Called by LangGraph on every node return that includes ``messages``.
    The reducer:
    1. Combines current + update into a single list
    2. Deduplicates by ``id`` (later replaces earlier)
    3. Applies a rolling window: keeps last 10 messages
    4. Preserves ALL milestone-tagged messages regardless of window

    Parameters
    ----------
    current:
        Current message list in state (or ``None`` on first turn).
    update:
        New message(s) from the node return.  A single ``MessageEntry``
        is treated as a one-element list.

    Returns
    -------
    Truncated, deduplicated message list.
    """
    full: list[MessageEntry] = (current or []) + (
        update if isinstance(update, list) else [update]
    )

    # Dedup by ID — later replaces earlier
    seen: dict[str, int] = {}
    deduped: list[MessageEntry] = []
    for msg in full:
        mid = msg.id
        if mid in seen:
            deduped[seen[mid]] = msg  # replace
            continue
        seen[mid] = len(deduped)
        deduped.append(msg)

    # Rolling window: keep last 10 + all milestones
    cutoff = max(0, len(deduped) - 10)
    kept: list[MessageEntry] = []
    for i, msg in enumerate(deduped):
        if i >= cutoff or msg.milestone:
            kept.append(msg)
    return kept


def tool_results_reducer(
    current: list[ToolResult] | None,
    update: list[ToolResult] | None,
) -> list[ToolResult]:
    """Append-only reducer with hard bound at 20 entries.

    Prevents unbounded ``tool_results`` growth when the DAG loops
    many times (dag_splitter generations).  Older entries are dropped
    when the list exceeds the bound.

    ``current`` is the accumulated list, ``update`` is the new batch
    (typically a single-element list from ``tool_executor``).
    """
    combined = (current or []) + (update or [])
    return combined[-20:]


# ============================================================================
# Tiered State TypedDicts
# ============================================================================


class PersistentContext(TypedDict, total=False):
    """Data that lives across conversation turns.

    **Lifecycle**: Created at session start → updated rarely (e.g.
    when user approves a new tool) → checkpointed every turn.

    **Migration**: These fields were previously flat in ``AgentState``.
    Now they live under ``state["persistent"]``.
    """

    session_id: str
    user_context: dict[str, Any]
    approved_tools: list[str]
    config_overrides: dict[str, Any]


class WorkingMemory(TypedDict, total=False):
    """Short-term data scoped to the current task or DAG batch.

    **Lifecycle**: Created when a user query is received → updated
    through intent parsing, planning, and tool execution → cleared
    when the final response is delivered (or when the conversation
    moves to a new query).

    **Migration**: These fields were previously in ``AgentState``
    at the top level.  Now they live under ``state["working"]``.
    """

    messages: Annotated[list[MessageEntry], messages_reducer]
    current_plan: ExecutionGraph
    tool_results_buffer: Annotated[list[ToolResult], tool_results_reducer]
    gathered_requirements: dict[str, Any]


class EphemeralFlags(TypedDict, total=False):
    """Turn-scoped routing and control flags.

    **Lifecycle**: Set before a node runs → read by routing functions
    → cleared before the next node executes.  These are NEVER
    checkpointed (they're not in the top-level ``AgentState``; LangGraph
    only checkpoints the top-level TypedDict's fields).

    **Migration**: These were previously ``_``-prefixed fields in
    ``AgentState`` (``_routing_decision``, ``_tool_executed_in_turn``,
    etc.).  Now they live outside the checkpointed state entirely,
    communicated via node return values during execution.
    """

    routing_decision: str
    execution_mode: str
    query_type: str
    tool_executed_in_turn: bool
    pending_tasks: list[str]
    failed_tasks: list[str]
    tool_retry_counts: dict[str, int]
    safety_result: dict[str, Any]
    needs_clarification: bool
    clarification_reason: str


# ============================================================================
# The unified AgentState — what LangGraph actually checkpoints
# ============================================================================


class AgentState(TypedDict):
    """Top-level state schema that LangGraph serialises.

    By grouping fields into nested TypedDicts, unchanged tiers are
    serialised as references rather than full payloads, reducing
    checkpoint size.

    ``ephemeral`` is deliberately **absent** from this TypedDict.
    Ephemeral flags are communicated via node return values during
    execution; LangGraph only checkpoints the fields declared here.
    This is the core optimisation: routing state that changes every
    node doesn't bloat the checkpoint database.

    Extending
    ---------
    Add new fields to the appropriate tier TypedDict above, then
    add them to this ``AgentState``.  If the field changes on every
    node (routing decisions, safety scores), it belongs in
    ``EphemeralFlags`` (outside the checkpoint).  If it changes
    once per turn (messages, plans), it belongs in ``WorkingMemory``.
    If it rarely changes (user config), it belongs in
    ``PersistentContext``.
    """

    persistent: PersistentContext
    working: WorkingMemory
    cost: CostTracker
