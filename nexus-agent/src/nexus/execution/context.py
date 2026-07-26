"""
Immutable Versioned ExecutionContext — Foundation for time-travel debugging and branching.

Every node receives ``Context(v)`` and returns ``Context(v+1)`` via ``StatePatch``.
No node ever mutates state in place.

``StatePatch`` describes the changes to apply to produce the next context.
This enables time-travel (replay from any version), branching (fork from any version),
and full event sourcing (every mutation is a recorded event).

No hardcoded field names. The context snapshot is a generic dict, versioned by integer.
``from_state()`` and ``to_state_update()`` dynamically bridge between LangGraph's
AgentState and this immutable ExecutionContext.

Note: ``ir_stack`` was previously a typed ``IRStack`` (4-layer IR). Since the
refactoring to Logical/Physical IR, it is now a generic dict for backward
compatibility with persisted state.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


# ============================================================================
# State Stores — replace flat _executor_results dict
# ============================================================================


class ToolResult(BaseModel):
    """Result of a single tool execution stored in ResultStore."""
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(description="Task identifier")
    status: str = Field(description="'success', 'error', or 'skipped'")
    data: Any = Field(default=None, description="Result data")
    error: str | None = Field(default=None, description="Error message if failed")


class ResultStore(BaseModel):
    """Transient data: tool outputs and aggregates.

    Replaces the flat ``_executor_results`` dict with structured storage.
    """
    model_config = ConfigDict(extra="forbid")

    _by_task: dict[str, ToolResult] = PrivateAttr(default_factory=dict)
    _by_entity: dict[str, dict[str, Any]] = PrivateAttr(default_factory=dict)
    _aggregates: dict[str, Any] = PrivateAttr(default_factory=dict)

    def store_task(self, task_id: str, entity_key: str | None, result: ToolResult) -> None:
        """Store a tool result and optionally index by entity key."""
        self._by_task[task_id] = result
        if entity_key and result.status == "success":
            self._by_entity.setdefault(entity_key, {}).update(result.data or {})

    def get_task(self, task_id: str) -> ToolResult | None:
        """Retrieve a stored task result."""
        return self._by_task.get(task_id)

    def store_aggregate(self, agg_id: str, data: Any) -> None:
        """Store an aggregate result."""
        self._aggregates[agg_id] = data

    def get_aggregate(self, agg_id: str) -> Any:
        """Retrieve an aggregate result."""
        return self._aggregates.get(agg_id)


class ArtifactStore(BaseModel):
    """Permanent side-effects: bookmarks, reports, files."""
    model_config = ConfigDict(extra="forbid")

    _artifacts: list[dict[str, Any]] = PrivateAttr(default_factory=list)

    def create(self, artifact_type: str, payload: dict[str, Any]) -> None:
        """Record a new artifact."""
        artifact = {"type": artifact_type, "payload": payload}
        self._artifacts.append(artifact)

    def list_by_type(self, artifact_type: str) -> list[dict[str, Any]]:
        """List artifacts by type."""
        return [a for a in self._artifacts if a["type"] == artifact_type]


class ExecutionSession(BaseModel):
    """A scoped execution session with results and artifacts."""
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(description="Session identifier")
    active_collections: dict[str, list[Any]] = Field(
        default_factory=dict,
        description="Named data collections for iteration",
    )
    results: ResultStore = Field(default_factory=ResultStore, description="Task results store")
    artifacts: ArtifactStore = Field(default_factory=ArtifactStore, description="Artifacts store")


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


class ExecutionContext(BaseModel):
    """Immutable versioned context — the only state shape nodes interact with.

    Attributes:
        version: Monotonic version counter.
        parent_version: The version this context was derived from.
        snapshot: The full state dict at this version.
        ir_stack: Generic dict for backward-compatible IR stack data.
        created_at: ISO timestamp of context creation.
    """
    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=0, description="Monotonic version counter")
    parent_version: int = Field(default=0, description="Parent version (0 = root)")
    snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description="Full state snapshot at this version",
    )
    ir_stack: dict[str, Any] = Field(
        default_factory=dict,
        description="IR stack data (backward-compatible dict)",
    )
    created_at: str = Field(default="", description="ISO timestamp")

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> ExecutionContext:
        """Rebuild an ExecutionContext from any AgentState-shaped dict."""
        import time

        raw_ir = state.get("_ir_stack", {})
        if isinstance(raw_ir, dict):
            ir_stack = dict(raw_ir)
        elif hasattr(raw_ir, "model_dump"):
            ir_stack = dict(raw_ir.model_dump())
        else:
            ir_stack = {}

        return cls(
            version=state.get("_context_version", 1),
            parent_version=max(0, state.get("_context_version", 1) - 1),
            snapshot=dict(state),
            ir_stack=ir_stack,
            created_at=str(time.time()),
        )

    def to_state_update(self) -> dict[str, Any]:
        """Produce the canonical subset of AgentState fields that changed."""
        return {
            "_ir_stack": self.ir_stack,
            "_context_version": self.version,
            "_context_snapshot": self.snapshot,
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

        return ExecutionContext(
            version=patch.version,
            parent_version=self.version,
            snapshot=new_snapshot,
            ir_stack=new_ir,
            created_at=self.created_at,
        )

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
            created_at=self.created_at,
        )
