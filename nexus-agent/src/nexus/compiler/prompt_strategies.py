"""Declarative progressive compression strategies for prompt budget overflow.

When the compiled prompt exceeds the token budget, these strategies
are applied in order until the budget is met or all strategies are exhausted.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import replace
from typing import Any

from nexus.compiler.context_ir import ContextIR, ContextSection, VERBOSE_FIELDS as _VERBOSE_FIELDS


class CompressionStrategy(ABC):
    """Base class for progressive compression strategies."""

    @abstractmethod
    def apply(self, ir: ContextIR, metrics: dict[str, Any]) -> tuple[ContextIR, dict[str, Any]]:
        """Apply this strategy to reduce the context footprint."""


class FieldCompressionStrategy(CompressionStrategy):
    """Remove verbose string fields from artifact projections.

    Drops fields matching _VERBOSE_FIELDS (description, summary, etc.)
    from all artifact data dicts.
    """

    def apply(self, ir: ContextIR, metrics: dict[str, Any]) -> tuple[ContextIR, dict[str, Any]]:
        new_items = []
        for item in ir.items:
            if item.section == ContextSection.ARTIFACTS and item.projection:
                new_data = {k: v for k, v in item.projection.data.items() if k.lower() not in _VERBOSE_FIELDS}
                new_items.append(replace(item, projection=replace(item.projection, data=new_data)))
            else:
                new_items.append(item)
        metrics["strategy_field_drop"] = True
        return replace(ir, items=tuple(new_items)), metrics


class ArtifactPruningStrategy(CompressionStrategy):
    """Keep only the most recent 3 artifact projections."""

    def apply(self, ir: ContextIR, metrics: dict[str, Any]) -> tuple[ContextIR, dict[str, Any]]:
        artifacts = [i for i in ir.items if i.section == ContextSection.ARTIFACTS]
        if len(artifacts) > 3:
            remaining = artifacts[-3:]
            new_items = [i for i in ir.items if i.section != ContextSection.ARTIFACTS] + remaining
            metrics["strategy_artifact_prune"] = True
            return replace(ir, items=tuple(new_items)), metrics
        return ir, metrics


# Ordered list: strategies are tried in sequence until budget is met
PROGRESSIVE_STRATEGIES: list[CompressionStrategy] = [
    FieldCompressionStrategy(),
    ArtifactPruningStrategy(),
]
