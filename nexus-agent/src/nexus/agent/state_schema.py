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


class MessageHistory(BaseModel):
    """Ordered, deduplicated, bounded message list with convenience methods.

    Replaces the raw ``list[MessageEntry]`` for ``messages`` in state.
    Wraps the rolling-window reducer logic into a class so nodes can
    call ``append()``, ``search()``, or ``truncate()`` directly without
    reimplementing the dedup/truncation logic.

    Lifecycle
    ---------
    Created empty at session start → appended to on every turn →
    automatically truncated to last 10 + milestones.

    Usage::

        history = MessageHistory()
        history.append("user", "Hello")
        history.append("assistant", "Hi there!", milestone=True)
        for msg in history.recent(5):
            print(msg.content)

    Serialisation
    -------------
    ``BaseModel`` serialisation means LangGraph's checkpointer can store
    and restore ``MessageHistory`` natively via ``model_dump()`` /
    ``model_validate()``.
    """

    entries: list[MessageEntry] = Field(default_factory=list, description="Ordered message list")

    def append(self, role: str, content: str, milestone: bool = False) -> MessageEntry:
        """Add a new message, deduplicate by ID, then apply rolling window.

        Returns the created ``MessageEntry`` so callers can inspect its ``id``.
        """
        entry = MessageEntry(role=role, content=content, milestone=milestone)
        return self.merge(entry)

    def merge(self, update: MessageEntry | list[MessageEntry]) -> MessageEntry | list[MessageEntry]:
        """Merge one or more messages into this history (dedup + truncate).

        Called by LangGraph's ``messages_reducer`` under the hood, but
        also available directly for nodes that want to add messages
        without going through the reducer.
        """
        combined = self.entries + (update if isinstance(update, list) else [update])

        # Dedup by ID — later replaces earlier
        seen: dict[str, int] = {}
        deduped: list[MessageEntry] = []
        for msg in combined:
            mid = msg.id
            if mid in seen:
                deduped[seen[mid]] = msg
                continue
            seen[mid] = len(deduped)
            deduped.append(msg)

        # Rolling window: keep last 10 + all milestones
        cutoff = max(0, len(deduped) - 10)
        self.entries = [
            msg for i, msg in enumerate(deduped)
            if i >= cutoff or msg.milestone
        ]

        if isinstance(update, list):
            return update
        return update

    def recent(self, n: int = 5) -> list[MessageEntry]:
        """Return the last ``n`` messages."""
        return self.entries[-n:]

    def search(self, text: str, field: str = "content") -> list[MessageEntry]:
        """Find messages where ``field`` contains ``text`` (case-insensitive)."""
        text_lower = text.lower()
        return [
            m for m in self.entries
            if text_lower in getattr(m, field, "").lower()
        ]

    def last_user_message(self) -> str:
        """Return the content of the most recent user message, or ''."""
        for msg in reversed(self.entries):
            if msg.role == "user":
                return msg.content
        return ""

    def count_by_role(self) -> dict[str, int]:
        """Return a dict mapping role → count."""
        counts: dict[str, int] = {}
        for msg in self.entries:
            counts[msg.role] = counts.get(msg.role, 0) + 1
        return counts

    def truncate(self, keep: int = 10) -> None:
        """Keep only the last ``keep`` messages plus milestones."""
        cutoff = max(0, len(self.entries) - keep)
        self.entries = [
            msg for i, msg in enumerate(self.entries)
            if i >= cutoff or msg.milestone
        ]

    def lazy_load(self, source: str | None = None) -> None:
        """Placeholder for future deferred loading from an external store.

        Args:
            source: Optional URI or session ID to load from.
        """
        pass

    def __len__(self) -> int:
        return len(self.entries)

    def __getitem__(self, idx: int) -> MessageEntry:
        return self.entries[idx]

    def __iter__(self):
        return iter(self.entries)


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

    messages: Annotated[MessageHistory, messages_reducer]
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
# Ephemeral fields — never persisted to the checkpointer
# ============================================================================

# Fields that are cleared between turns — not persisted across checkpoints.
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
    "_pending_splits",
    "_dag_generation",
    "_split_tools",
    "_query_type",
    "_force_query_type",
    "_filtered_tools",
    "_preferred_tools",
    "completed_task_ids",
    "_executor_failed",
    "_executor_results",
    "_executor_all_success",
    "_tool_retry_counts",
    "_pending_tasks",
    "_execution_plan",
]


# ============================================================================
# The unified AgentState — what LangGraph actually checkpoints
# ============================================================================


class AgentState(TypedDict, total=False):
    """Top-level state schema that LangGraph serialises.

    By grouping fields into nested TypedDicts, unchanged tiers are
    serialised as references rather than full payloads, reducing
    checkpoint size.

    ``total=False`` allows runtime flat fields during the migration
    from ``state.py`` — nodes can access both nested tiers and flat
    fields without type errors.

    ``ephemeral`` flags are deliberately absent.  They are communicated
    via node return values during execution; LangGraph only checkpoints
    the fields declared here.  This is the core optimisation: routing
    state that changes every node doesn't bloat the checkpoint database.

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

    # New 3-tier structure (preferred — migrated toward)
    persistent: PersistentContext
    working: WorkingMemory
    cost: CostTracker

    # Legacy flat fields (backward compat — migrate to tiers)
    messages: Annotated[list[dict[str, Any]], messages_reducer]
    session_id: str
    user_context: dict[str, Any]
    plan: list[dict[str, Any]] | None
    current_step_index: int
    gathered_requirements: dict[str, Any]
    available_tools: list[dict[str, Any]]
    pending_approval: dict[str, Any] | None
    iteration_count: int
    scratchpad: str
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
    reflection_history: list[dict[str, Any]]
    task_difficulty: float | None
    total_cost_usd: float
    _cost_breakdown: dict[str, Any]
    _total_tokens: int
    _max_concurrent_tasks: int | None
    _pending_splits: list[str]
    _dag_generation: int
    dag_tasks: list[dict[str, Any]]
    dag_results: dict[str, Any]
    completed_task_ids: list[str]
    dag_phase: str
    _routing_decision: str
    _tool_executed_in_turn: bool
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
    _force_query_type: str
    _query_type: str
    _filtered_tools: list[dict[str, Any]] | None
    _preferred_tools: list[str]
    _split_tools: list[str]
    tool_results_ref: str
    _executor_failed: list[str]
    _executor_results: dict[str, Any]
    _executor_all_success: bool
    _tool_retry_counts: dict[str, int]
    _pending_tasks: list[str]
    _execution_plan: dict[str, Any]
