"""Immutable Versioned ExecutionContext — Foundation for time-travel debugging and branching.

Every node receives ``Context(v)`` and returns ``Context(v+1)`` via ``StatePatch``.
No node ever mutates state in place.

``StatePatch`` describes the changes to apply to produce the next context.
This enables time-travel (replay from any version), branching (fork from any version),
and full event sourcing (every mutation is a recorded event).

No hardcoded fields. The context snapshot is a generic dict, versioned by integer.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StatePatch(BaseModel):
    """A description of changes to produce the next ExecutionContext.

    Attributes:
        version: The target version (current context version + 1).
        updates: Field-level updates to merge into context snapshot.
        removes: Keys to remove from context snapshot.
        ir_stack_update: Optional IRStack updates as a dict.
    """

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
        description="IRStack fields to update (intents, goals, operations, execution_plan)",
    )


class ExecutionContext(BaseModel):
    """Immutable versioned context — the only state shape nodes interact with.

    Nodes receive an ``ExecutionContext`` and return a ``StatePatch`` describing
    what changes to apply. The framework applies the patch to produce the next context.

    Attributes:
        version: Monotonic version counter.
        parent_version: The version this context was derived from.
        snapshot: The full state dict at this version.
        ir_stack: Serialized IRStack data (intents, goals, operations, execution_plan).
        created_at: ISO timestamp of context creation.
    """

    version: int = Field(default=0, description="Monotonic version counter")
    parent_version: int = Field(default=0, description="Parent version (0 = root)")
    snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description="Full state snapshot at this version",
    )
    ir_stack: dict[str, Any] = Field(
        default_factory=dict,
        description="IRStack data: {intents, goals, operations, execution_plan}",
    )
    created_at: str = Field(default="", description="ISO timestamp")

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

    def branch(self) -> ExecutionContext:
        """Create a branch from this context (same version, new parent).

        Useful for speculative execution or what-if analysis.
        """
        return ExecutionContext(
            version=self.version,
            parent_version=self.version,
            snapshot=dict(self.snapshot),
            ir_stack=dict(self.ir_stack),
            created_at=self.created_at,
        )

    @staticmethod
    def from_snapshot(snapshot: dict[str, Any]) -> ExecutionContext:
        """Create a root ExecutionContext from an initial state dict."""
        import time
        ir_data = {}
        if "_ir_stack" in snapshot:
            ir_data = snapshot.pop("_ir_stack", {})
        return ExecutionContext(
            version=1,
            parent_version=0,
            snapshot=snapshot,
            ir_stack=ir_data if isinstance(ir_data, dict) else {},
            created_at=str(time.time()),
        )
