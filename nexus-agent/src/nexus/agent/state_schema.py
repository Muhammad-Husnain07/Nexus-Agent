"""Production-grade AgentState schema — tiered memory, type-safe, reducer-optimized.

P1-B.1: AGENT_STATE_SCHEMA_VERSION is the AgentState contract version —
checkpoints carry it (plus the architecture fingerprint) in
``_contract_meta``; a checkpoint is only resumed under the exact contract
it was created for.

Lifecycle Architecture
======================

The state is split into three tiers based on lifespan:

                    ┌──────────────────────────────────────────────┐
                    │         Persistent Context                  │
                    │  (survives across conversation turns)       │
                    │  session_id, user_context, config_overrides │
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
                    │  (cleared every turn)                        │
                    │  routing decisions, retry counts, safety     │
                    │  NOT checkpointed across node boundaries.    │
                    └──────────────────────────────────────────────┘
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

# P1-B.1: the AgentState contract version — carried in checkpoint
# ``_contract_meta`` alongside the architecture fingerprint. Bump when the
# state schema changes incompatibly; old checkpoints then refuse resume.
AGENT_STATE_SCHEMA_VERSION = "1"

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict


# ============================================================================
# Pydantic Models (type-safe nested objects)
# ============================================================================


class ToolResult(BaseModel):
    """A single tool execution result with metadata for observability."""
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    status: Literal["success", "error", "timeout", "validation_error"]
    data: Any = None
    error: str | None = None
    task_id: str = ""
    duration_ms: float = 0.0
    cost_usd: float = 0.0
    dag_generation: int = 0


class ExecutionNode(BaseModel):
    """A node in the execution DAG (the task graph, not LangGraph's own graph)."""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Unique task identifier")
    tool_name: str | None = Field(default=None, description="Tool to invoke")
    description: str = Field(default="", description="Human-readable description")
    inputs: dict[str, Any] = Field(default_factory=dict, description="Tool input parameters")
    depends_on: list[str] = Field(default_factory=list, description="Prerequisite node IDs")
    status: Literal["pending", "running", "completed", "failed", "skipped"] = "pending"
    result: ToolResult | None = Field(default=None, description="Execution result when done")
    retry_count: int = Field(default=0, ge=0, description="Number of retries so far")
    max_retries: int = Field(default=2, ge=0, description="Max retries before giving up")


class ExecutionGraph(BaseModel):
    """Full DAG structure for observability and routing."""
    model_config = ConfigDict(extra="forbid")

    nodes: dict[str, ExecutionNode] = Field(
        default_factory=dict, description="All nodes keyed by ID",
    )
    generation: int = Field(default=0, description="DAG expansion generation")
    concurrent_budget: int = Field(default=5, description="Max parallel executions")
    split_tools: list[str] = Field(
        default_factory=list, description="Tools that have already been split (recursion guard)",
    )

    def add_node(self, node: ExecutionNode) -> None:
        self.nodes[node.id] = node

    def add_nodes(self, nodes: list[ExecutionNode]) -> None:
        for n in nodes:
            self.nodes[n.id] = n

    def ready_nodes(self) -> list[ExecutionNode]:
        return [
            n for n in self.nodes.values()
            if n.status == "pending"
            and all(
                self.nodes.get(d) and self.nodes[d].status == "completed"
                for d in n.depends_on
            )
        ]

    def remaining(self) -> list[ExecutionNode]:
        return [n for n in self.nodes.values() if n.status in ("pending", "running")]

    def failed(self) -> list[str]:
        return [n.id for n in self.nodes.values() if n.status == "failed"]

    def update_result(self, task_id: str, result: ToolResult) -> None:
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
                node.status = "pending"

    def mark_skipped(self, task_id: str) -> None:
        node = self.nodes.get(task_id)
        if node:
            node.status = "skipped"


class CostTracker(BaseModel):
    """Token and cost accumulator with per-node breakdown."""
    model_config = ConfigDict(extra="forbid")

    total_cost_usd: float = 0.0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    per_node: dict[str, float] = Field(
        default_factory=dict, description="node_name → accumulated cost",
    )

    def record(self, node_name: str, cost_usd: float = 0.0, tokens: int = 0, inp: int = 0, out: int = 0) -> None:
        self.total_cost_usd += cost_usd
        self.total_tokens += tokens
        self.input_tokens += inp
        self.output_tokens += out
        self.per_node[node_name] = self.per_node.get(node_name, 0.0) + cost_usd

    def budget_remaining(self, budget: float) -> float:
        return max(0.0, budget - self.total_cost_usd)


class MessageEntry(BaseModel):
    """A single message with metadata for efficient truncation and dedup."""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique message identifier")
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    milestone: bool = Field(default=False, description="Never truncated by rolling window")
    created_at: float = Field(
        default_factory=lambda: datetime.now(timezone.utc).timestamp(),
        description="Unix timestamp of creation",
    )


class MessageHistory(BaseModel):
    """Ordered, deduplicated, bounded message list with convenience methods."""
    model_config = ConfigDict(extra="forbid")

    entries: list[MessageEntry] = Field(default_factory=list, description="Ordered message list")

    def append(self, role: str, content: str, milestone: bool = False) -> MessageEntry:
        entry = MessageEntry(role=role, content=content, milestone=milestone)
        return self.merge(entry)

    def merge(self, update: MessageEntry | list[MessageEntry]) -> MessageEntry | list[MessageEntry]:
        combined = self.entries + (update if isinstance(update, list) else [update])
        seen: dict[str, int] = {}
        deduped: list[MessageEntry] = []
        for msg in combined:
            mid = msg.id
            if mid in seen:
                deduped[seen[mid]] = msg
                continue
            seen[mid] = len(deduped)
            deduped.append(msg)
        cutoff = max(0, len(deduped) - 10)
        self.entries = [msg for i, msg in enumerate(deduped) if i >= cutoff or msg.milestone]
        if isinstance(update, list):
            return update
        return update

    def recent(self, n: int = 5) -> list[MessageEntry]:
        return self.entries[-n:]

    def last_user_message(self) -> str:
        for msg in reversed(self.entries):
            if msg.role == "user":
                return msg.content
        return ""

    def truncate(self, keep: int = 10) -> None:
        cutoff = max(0, len(self.entries) - keep)
        self.entries = [msg for i, msg in enumerate(self.entries) if i >= cutoff or msg.milestone]

    def __len__(self) -> int:
        return len(self.entries)

    def __getitem__(self, idx: int) -> MessageEntry:
        return self.entries[idx]

    def __iter__(self):
        return iter(self.entries)


# ============================================================================
# Reducers
# ============================================================================


def _get_msg_id(msg: Any) -> str:
    if isinstance(msg, dict):
        return msg.get("id", "") or ""
    return getattr(msg, "id", "") or ""


def _get_msg_milestone(msg: Any) -> bool:
    if isinstance(msg, dict):
        return msg.get("_milestone", False) or msg.get("milestone", False)
    return getattr(msg, "milestone", False) or False


def messages_reducer(
    current: list[Any] | None,
    update: list[Any] | dict[str, Any] | None,
) -> list[Any]:
    """Rolling-window message reducer — handles both dicts and MessageEntry."""
    full: list[Any] = (current or []) + (update if isinstance(update, list) else [update])
    for m in full:
        if isinstance(m, dict):
            m.setdefault("id", str(uuid.uuid4()))
    seen: dict[str, int] = {}
    deduped: list[Any] = []
    for msg in full:
        mid = _get_msg_id(msg)
        if mid and mid in seen:
            deduped[seen[mid]] = msg
            continue
        if mid:
            seen[mid] = len(deduped)
        deduped.append(msg)
    cutoff = max(0, len(deduped) - 10)
    kept: list[Any] = []
    for i, msg in enumerate(deduped):
        if i >= cutoff or _get_msg_milestone(msg):
            kept.append(msg)
    return kept


def tool_results_reducer(
    current: list[ToolResult] | None,
    update: list[ToolResult] | None,
) -> list[ToolResult]:
    """Append-only reducer with hard bound at 20 entries."""
    combined = (current or []) + (update or [])
    return combined[-20:]


# ============================================================================
# Tiered State TypedDicts
# ============================================================================


class PersistentContext(TypedDict, total=False):
    """Data that lives across conversation turns."""

    session_id: str
    user_context: dict[str, Any]
    approved_tools: list[str]
    config_overrides: dict[str, Any]


class WorkingMemory(TypedDict, total=False):
    """Short-term data scoped to the current task or DAG batch."""

    messages: Annotated[MessageHistory, messages_reducer]
    current_plan: ExecutionGraph
    tool_results_buffer: Annotated[list[ToolResult], tool_results_reducer]
    gathered_requirements: dict[str, Any]


class EphemeralFlags(TypedDict, total=False):
    """Turn-scoped routing and control flags — NOT checkpointed."""

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
# Ephemeral fields — cleared between turns, not persisted to checkpointer
# ============================================================================

_EPHEMERAL_FIELDS: list[str] = [
    "_routing_decision",
    "_tool_executed_in_turn",
    "_safety_result",
    "tool_results",
    "errors",       # flat backward-compat, not typed in AgentState

    "_invocation_id",  # A3/P1-A: per-invocation identity (memory provenance)

    "_query_type",
    "_force_query_type",
    "_goals",
    "_needs_requirements",
    "_preferred_tools",
    "_plan_validator_report",
    "_plan_validator_action",
    "_plan_validator_errors",
    "_plan_validator_rounds",
    "_compile_errors",
    "_compile_retry_count",
    "_invocation_budget",
    "_invocation_status",
    "_response_coverage",
    "_execution_strategy",
    "_execution_strategy_reasons",
    "_background_execution",
    "_background_task_id",
    "_execution_plan",
    "_needs_replan",
    "_replan_rounds",
    "_replan_context",
    "_recovery_decision",
    "_recovery_action",
    "_approval_denied_blocking",
    "_executor_failed",
    "_executor_failed",
    "_executor_all_success",
    "_tool_retry_counts",
    "_pending_tasks",
    # Compiler IR stack
    # NOTE: _ir_stack and _context_version are NOT ephemeral — they persist
    # across incremental re-compilations (Roslyn-style).
    # _context_snapshot IS ephemeral — rebuilt each turn from AgentState checkpoint.
    "_context_snapshot",
    "_extraction_result",
    "_validation_result",
    "_binding_report",
    "_detected_intents",
    "_response_status",
    "_map_degradations",
    "_ready_to_plan",
    "_needs_clarification",
    "_clarification_asked",
    "_needs_approval",
    "_pending_approval_tools",
    "_approval_granted",
    "_recovery_available",
    "_recovery_failed_tasks",
    "_total_retry_count",
    # Cost tracking
    "_total_tokens",
    "_cost_breakdown",
    # Approval decision (cleared by approval_gate_node after reading)
    "_approval_decision",
    # Approval request timestamp (set when approval is first requested)
    "_approval_requested_at",
    # Multi-stage approval chain state
    "_approval_chain_state",
    # Requirement collector state
    "_clarification_slots",
    "_clarification_rounds",
    "_clarification_history",
    "_clarification_consumed_msgs",
    "_route_to_planner",
    "_route_to_compiler",
    "_bypass_workflow",
    "_route_to_router",
    "_route_to_gate",
    "_domain_hint",
    # Interactive workflow state
    # NOTE: The workflow context fields (_workflow_step, _workflow_collected,
    # _workflow_definition, etc.) MUST NOT be ephemeral. They must persist
    # across turns so the state machine can resume.
    # Only the final _structured_payload is ephemeral (consumed by ResponseNode
    # in the same turn it is produced).
    "_structured_payload",
    # Synthesis recovery: set when the LLM synthesizer failed and the
    # Artifact Renderer produced the answer (never an execution error).
    "_synthesis_failed",
    # Per-stage timing metrics (node → ms) for latency attribution.
    "_stage_metrics",
    # Immutable append-only execution-event trail (bounded, replayable).
    "_execution_events",
    # ExecutionBudget degradation flag (stage that exceeded its budget).
    "_budget_exceeded",
]


# ============================================================================
# The unified AgentState — what LangGraph actually checkpoints
# ============================================================================


class AgentState(TypedDict, total=False):
    """Top-level state schema that LangGraph serialises.

    ``total=False`` allows the dict to carry ephemeral fields at runtime
    that are not checkpointed.  Ephemeral flags are communicated via
    node return values and live in ``_EPHEMERAL_FIELDS`` — they are
    cleared between turns by the runner.
    """

    # New 3-tier structure (preferred — migrate toward)
    persistent: PersistentContext
    working: WorkingMemory
    cost: CostTracker

    # Flat fields used by the 5-node production graph
    messages: Annotated[list[dict[str, Any]], messages_reducer]
    session_id: str
    iteration_count: int
    final_response: str | None
    intent: dict[str, Any] | None
    errors: list[str]
    intent_analysis: dict[str, Any] | None
    response_type: str
    reflection_feedback: str
    working_memory: dict[str, Any]
    gathered_requirements: dict[str, Any]
    plan: list[dict[str, Any]] | None
    total_cost_usd: float
    _cost_breakdown: dict[str, Any]
    _total_tokens: int
    # All _-prefixed fields must also be in _EPHEMERAL_FIELDS above

    # Graph routing & execution state
    _routing_decision: str
    _tool_executed_in_turn: bool
    _safety_result: dict[str, Any]
    _force_query_type: str
    _query_type: str
    _goals: list[str]
    _needs_requirements: bool
    _preferred_tools: list[str]
    _plan_validator_report: dict[str, Any]
    _plan_validator_action: str
    _plan_validator_errors: list[str]
    _plan_validator_rounds: int
    _compile_errors: list[str]
    _compile_retry_count: int
    _invocation_budget: dict[str, Any]
    _invocation_status: str
    _invocation_id: str
    _response_coverage: float
    _execution_strategy: str
    _execution_strategy_reasons: list[str]
    _background_execution: bool
    _background_task_id: str
    _execution_plan: dict[str, Any]
    _needs_replan: bool
    _replan_rounds: int
    _replan_context: dict[str, Any]
    _recovery_decision: dict[str, Any]
    _recovery_action: str
    _approval_denied_blocking: bool
    _executor_failed: list[str]
    _executor_all_success: bool
    _tool_retry_counts: dict[str, int]
    _pending_tasks: list[str]

    # Tool execution state (also in _EPHEMERAL_FIELDS)
    tool_results: list[dict[str, Any]]
    errors: list[str]

    # StructuredContext (extraction → validation → planning)
    _extraction_result: dict[str, Any]
    _structured_context: dict[str, Any]
    _validation_result: dict[str, Any]
    _ready_to_plan: bool
    _needs_clarification: bool

    # HITL approval
    _needs_approval: bool
    _pending_approval_tools: list[dict[str, Any]]
    _approval_decision: str
    _approval_granted: bool
    _approval_requested_at: float
    _approval_chain_state: dict[str, Any]

    # Compiler IR (persistent across incremental re-compilations)
    _ir_stack: dict[str, Any]
    _context_version: int
    _context_snapshot: dict[str, Any]

    # P1-B.1: checkpoint compatibility contract — architecture fingerprint
    # + state-schema version. A checkpoint is only resumed under the
    # contract it was created for; mismatches refuse safely.
    _contract_meta: dict[str, Any]

    # New 13-node compiler pipeline fields
    _logical_workflow: dict[str, Any]
    _execution_graph: dict[str, Any]
    _optimization_snapshots: list[dict[str, Any]]
    _graph_version: int
    _cost_estimate: float
    _latency_estimate_ms: int
    _within_budget: bool
    _estimate_warnings: list[str]
    _aggregated_results: dict[str, Any]
    _graph_patch: dict[str, Any] | None
    _memory_persisted: dict[str, Any]

    # P0-B: parameter/provenance binding ledger (BOUND/MISSING/AMBIGUOUS/
    # INVALID classification with candidate sources) — ephemeral per plan.
    _binding_report: dict[str, Any]

    # P0-C: structured intent decomposition (goals/entities/relationships —
    # the reviewer's DetectedIntentGraph) — the coverage check consumes it.
    _detected_intents: dict[str, Any]

    # P2-A.2: map-degradation ledger (dangling iterate_over stripped to a
    # single body — a lost fan-out is never invisible).
    _map_degradations: list[dict[str, Any]]

    # P1-B: explicit terminal response status (SUCCESS / PARTIAL_SUCCESS /
    # CLARIFICATION_REQUIRED / EXECUTION_FAILED / PLANNING_FAILED) — an
    # executable request never collapses into silent-success text.
    _response_status: str

    # Runtime-only ephemeral fields (carried in state but not in TypedDict)
    _total_retry_count: int
    _recovery_available: bool
    _recovery_failed_tasks: list
    _clarification_asked: dict

    # Requirement collector state
    _clarification_slots: dict[str, Any]
    _clarification_rounds: int
    _clarification_history: list[dict[str, Any]]
    _clarification_consumed_msgs: list[str]
    _route_to_planner: bool
    _route_to_compiler: bool
    _bypass_workflow: bool
    _route_to_router: bool
    _route_to_gate: bool
    _domain_hint: str | None

    # Interactive workflow state (multi-turn)
    _active_workflow_id: str | None
    _workflow_type: str
    _workflow_step: int
    _workflow_steps_total: int
    _workflow_collected: dict[str, Any]
    _workflow_history: list[dict[str, Any]]
    _workflow_next_action: str
    _workflow_definition: dict[str, Any]
    _structured_payload: dict[str, Any]
    _workflow_completed_steps: list[str]
    _workflow_captured: list[str]
    # Synthesis recovery: LLM synthesizer failed → Artifact Renderer answered.
    _synthesis_failed: bool
    # Per-stage timing metrics (node → ms) for latency attribution.
    _stage_metrics: dict[str, float]
    # Immutable append-only execution-event trail (bounded, replayable).
    _execution_events: list[dict]
    # ExecutionBudget degradation flag (stage that exceeded its budget).
    _budget_exceeded: str | None
    # Hybrid execution: dynamic-step planning markers (persist until captured)
    _workflow_dynamic_pending: str | None
    _workflow_dynamic_intent: str | None
    # Conversational approval checkpoint (persists across turns until decided)
    _approval_pending: dict[str, Any] | None
    _approval_checkpoint_context: str | None
    _approval_modification: str | None
