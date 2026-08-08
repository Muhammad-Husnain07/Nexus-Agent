"""OptimizationPass — deduplicates artifact projections by artifact_id."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from nexus.compiler.context_ir import ContextIR, ContextSection
from nexus.compiler.prompt_passes import CompilerPass


class OptimizationPass(CompilerPass):
    """Remove duplicate artifact projections from the context.

    If two ContextItems reference the same ``artifact_id``, only the
    first occurrence is kept.  Non-artifact items are preserved.
    """

    name = "optimization"
    requires: list[str] = ["selection"]
    produces: list[str] = ["deduplicated_items"]

    def run(self, ir: ContextIR, metrics: dict[str, Any], **kwargs: Any) -> tuple[ContextIR, dict[str, Any]]:
        seen: set[str] = set()
        unique: list = []
        for item in ir.items:
            if item.section == ContextSection.ARTIFACTS and item.projection:
                if item.projection.artifact_id in seen:
                    continue
                seen.add(item.projection.artifact_id)
            unique.append(item)
        metrics["dedup_removed"] = len(ir.items) - len(unique)
        return replace(ir, items=tuple(unique)), metrics
