"""
Immutable Versioned ExecutionContext — Foundation for time-travel debugging and branching.

Every node receives ``Context(v)`` and returns ``Context(v+1)`` via ``StatePatch``.
No node ever mutates state in place.

``StatePatch`` describes the changes to apply to produce the next context.
This enables time-travel (replay from any version), branching (fork from any version),
and full event sourcing (every mutation is a recorded event).

No hardcoded field names. The context is versioned by integer.
``from_state()`` and ``to_state_update()`` dynamically bridge between LangGraph's
AgentState and this immutable ExecutionContext.

**State Slimming**: ``from_state()`` strips static/redundant fields (e.g. ``available_tools``)
from the snapshot to prevent log bloat.  ExecutionContext fields that reference tools,
registry, or static schemas are prohibited — those live in ``GlobalContext`` and
``SessionContext`` respectively.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ============================================================================
# Fields that must NOT appear in ExecutionContext or StatePatch
# (they belong in GlobalContext or SessionContext instead)
# ============================================================================
_GLOBAL_CONTEXT_KEYS: frozenset[str] = frozenset({
    "compiled_graph", "ontology", "static_schemas", "registry_checksum",
})
_SESSION_CONTEXT_KEYS: frozenset[str] = frozenset({
    "user_context", "user_id", "policies", "memory_ids", "registry_version_checksum",
})

# Fields that are static/redundant and should be stripped from the lean snapshot
_STATIC_STRIP_FIELDS: frozenset[str] = frozenset({
    "available_tools",  # 12-tool array duplicated in every snapshot — lives in GlobalContext
    "tool_results",     # raw JSON payloads — bloat; ResponseNode reads ArtifactGraph instead
    "_executor_results",  # redundant hash-keyed dict — eliminated in favor of tool_results
})


def _is_global_or_session_key(key: str) -> bool:
    """Return True if a key belongs to GlobalContext or SessionContext."""
    return key in _GLOBAL_CONTEXT_KEYS or key in _SESSION_CONTEXT_KEYS


# ============================================================================
# StatePatch & ExecutionContext
# ============================================================================


class StatePatch(BaseModel):
    """A description of changes to produce the next ExecutionContext.

    Attributes:
        version: The target version (current context version + 1).
        updates: Field-level updates to merge into context snapshot.
        removes: Keys to remove from context snapshot.
        ir_stack_update: Optional dict of IR stack fields to update.
    """
    model_config = ConfigDict(extra="forbid")

    version: int = Field(description="Target context version (current + 1)")
    updates: dict[str, Any] = Field(
        default_factory=dict,
        description="Field-level updates to merge into context",
    )
    removes: list[str] = Field(
        default_factory=list,
        description="Keys to remove from context snapshot",
    )
    ir_stack_update: dict[str, Any] | None = Field(
        default=None,
        description="IR stack fields to update",
    )


_LEAN_SNAPSHOT_FIELDS: frozenset[str] = frozenset({
    "_query_type", "_routing_decision", "_executor_all_success",
    "_context_version", "iteration_count", "final_response",
    "response_type", "errors", "session_id",
    "_critique_rounds", "_requires_refinement", "_needs_clarification",
    "_approval_granted", "_ready_to_plan", "_tool_executed_in_turn",
    "_total_retry_count", "reflection_feedback", "gathered_requirements",
})


class ExecutionContext(BaseModel):
    """Immutable versioned context — lean, fast-moving state only.

    Attributes:
        version: Monotonic version counter.
        parent_version: The version this context was derived from.
        snapshot: Lean state dict (strips static/redundant fields).
        ir_stack: Generic dict for backward-compatible IR stack data.
        artifact_ids: List of artifact UUIDs produced in this context.
        execution_ids: List of execution event UUIDs.
        routing_decision: Current routing decision string.
        created_at: ISO timestamp of context creation.
    """
    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=0, description="Monotonic version counter")
    parent_version: int = Field(default=0, description="Parent version (0 = root)")
    snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description="Lean state snapshot (static fields excluded)",
    )
    ir_stack: dict[str, Any] = Field(
        default_factory=dict,
        description="IR stack data (backward-compatible dict)",
    )
    artifact_ids: list[str] = Field(
        default_factory=list,
        description="Artifact UUIDs produced in this context",
    )
    execution_ids: list[str] = Field(
        default_factory=list,
        description="Execution event UUIDs",
    )
    routing_decision: str = Field(
        default="continue",
        description="Current routing decision",
    )
    node_timeline: list[str] = Field(
        default_factory=list,
        description="Ordered list of node names executed in this context version",
    )
    # --- Phase 9 enrichment (typed; derived from snapshot via apply()) ---
    budget: dict[str, Any] = Field(
        default_factory=dict,
        description="Typed budget view (cost/latency caps + estimates)",
    )
    strategy: str = Field(
        default="", description="Selected execution strategy (Phase 4)"
    )
    checkpoints: dict[str, Any] = Field(
        default_factory=dict,
        description="Named checkpoints (approval/plan-validator decisions)",
    )
    artifacts: dict[str, Any] = Field(
        default_factory=dict,
        description="Artifact view: type → latest artifact ids (in-session)",
    )
    idempotency_key: str | None = Field(
        default=None,
        description="Provider-facing idempotency key — STABLE across retries "
        "and recovery attempts for the same logical operation (P0). The "
        "executor stamps it on the request when the tool declares an "
        "idempotency header.",
    )
    user_roles: list[str] = Field(
        default_factory=list,
        description="Roles of the invoking user (P0 authorization gate). "
        "The executor denies a capability whose metadata declares "
        "``allowed_roles`` that do not intersect the caller's roles.",
    )
    created_at: str = Field(default="", description="ISO timestamp")

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> ExecutionContext:
        """Rebuild an ExecutionContext from any AgentState-shaped dict.

        Strips static/redundant fields (``available_tools``) from the snapshot
        to keep context size small (< 5KB).
        """
        import time

        raw_ir = state.get("_ir_stack", {})
        if isinstance(raw_ir, dict):
            ir_stack = dict(raw_ir)
        elif hasattr(raw_ir, "model_dump"):
            ir_stack = dict(raw_ir.model_dump())
        else:
            ir_stack = {}

        # Build lean snapshot — only fields that actually change between nodes
        full_snapshot = dict(state)
        lean = {}
        for k, v in full_snapshot.items():
            if k in _STATIC_STRIP_FIELDS:
                continue  # skip bloat
            if k == "_context_snapshot":
                continue  # NEVER copy the old snapshot into the new one
            if k in _LEAN_SNAPSHOT_FIELDS or k.startswith("_") or k in (
                "messages", "tool_results", "dag_tasks",
                "_logical_workflow", "_execution_graph",
                "_extraction_result", "_validation_result",
                "_cost_estimate", "_preferred_tools",
                "intent", "intent_analysis",
            ):
                lean[k] = v

        return cls(
            version=state.get("_context_version", 1),
            parent_version=max(0, state.get("_context_version", 1) - 1),
            snapshot=lean,
            ir_stack=ir_stack,
            routing_decision=state.get("_routing_decision", "continue"),
            node_timeline=list(state.get("_node_timeline", [])),
            created_at=str(time.time()),
        )

    def to_state_update(self) -> dict[str, Any]:
        """Produce the canonical subset of AgentState fields that changed."""
        return {
            "_ir_stack": self.ir_stack,
            "_context_version": self.version,
            "_context_snapshot": self.snapshot,
            "_routing_decision": self.routing_decision,
            "_node_timeline": self.node_timeline,
        }

    def apply(self, patch: StatePatch) -> ExecutionContext:
        """Apply a StatePatch to produce the next ExecutionContext.

        Returns a NEW context with incremented version. The original is unchanged.
        """
        new_snapshot = dict(self.snapshot)
        new_snapshot.update(patch.updates)
        for key in patch.removes:
            new_snapshot.pop(key, None)

        new_ir = dict(self.ir_stack)
        if patch.ir_stack_update:
            new_ir.update(patch.ir_stack_update)

        # Typed derived views (Phase 9): budget/strategy/checkpoints/artifacts
        # are read FROM the snapshot — the context stays the single source.
        budget = {
            "cost_estimate_usd": float(new_snapshot.get("_cost_estimate", 0.0) or 0.0),
            "latency_estimate_ms": int(new_snapshot.get("_latency_estimate_ms", 0) or 0),
            "within_budget": bool(new_snapshot.get("_within_budget", True)),
        }
        checkpoints: dict[str, Any] = {}
        if new_snapshot.get("_plan_validator_action"):
            checkpoints["plan_validator"] = new_snapshot.get("_plan_validator_action", "")
        if new_snapshot.get("_approval_pending"):
            checkpoints["approval"] = "pending"

        return ExecutionContext(
            version=patch.version,
            parent_version=self.version,
            snapshot=new_snapshot,
            ir_stack=new_ir,
            artifact_ids=list(self.artifact_ids),
            execution_ids=list(self.execution_ids),
            routing_decision=self.routing_decision,
            node_timeline=list(self.node_timeline),
            budget=budget,
            strategy=str(new_snapshot.get("_execution_strategy", "") or ""),
            checkpoints=checkpoints,
            created_at=self.created_at,
        )

    def record_node(self, node_name: str) -> None:
        """Append a node name to the timeline (used by @context_node or graph wrapper)."""
        self.node_timeline.append(node_name)

    @classmethod
    def replay(cls, patches: list[StatePatch], initial: ExecutionContext | None = None) -> ExecutionContext:
        """Rebuild context by replaying a sequence of StatePatches from version 0."""
        ctx = initial if initial is not None else cls(version=0, parent_version=0, snapshot={})
        for patch in patches:
            if patch.version <= ctx.version:
                continue
            ctx = ctx.apply(patch)
        return ctx

    def branch(self) -> ExecutionContext:
        """Create a branch from this context for speculative execution."""
        return ExecutionContext(
            version=self.version,
            parent_version=self.version,
            snapshot=dict(self.snapshot),
            ir_stack=dict(self.ir_stack),
            artifact_ids=list(self.artifact_ids),
            execution_ids=list(self.execution_ids),
            routing_decision=self.routing_decision,
            node_timeline=list(self.node_timeline),
            budget=dict(self.budget),
            strategy=self.strategy,
            checkpoints=dict(self.checkpoints),
            artifacts=dict(self.artifacts),
            created_at=self.created_at,
        )
