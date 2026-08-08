"""TokenAwareCompressionPass — iteratively compresses artifact data to fit budget."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from nexus.compiler.context_ir import ContextIR, ContextSection, VERBOSE_FIELDS as _VERBOSE_FIELDS
from nexus.compiler.prompt_passes import CompilerPass


class TokenAwareCompressionPass(CompilerPass):
    """Iteratively compress artifact data until within token budget.

    Each iteration: render a mock prompt, estimate tokens, find the
    longest verbose field across all artifacts, truncate by 20%.
    Stops when budget is met or no compressible fields remain.
    """

    name = "compression"
    requires: list[str] = ["optimization"]
    produces: list[str] = ["compressed_items"]
    # Kwarg contract: the pipeline injects exactly these (no name dispatch)
    accepts: dict[str, str] = {
        "estimator": "token estimator",
        "renderer": "prompt renderer",
    }

    def run(self, ir: ContextIR, metrics: dict[str, Any], **kwargs: Any) -> tuple[ContextIR, dict[str, Any]]:
        estimator = kwargs.get("estimator")
        renderer = kwargs.get("renderer")
        target_budget = ir.budget_limit
        if not target_budget:
            return ir, metrics

        new_items = list(ir.items)

        while True:
            if estimator and renderer:
                mock_ir = ContextIR(items=tuple(new_items))
                rendered = renderer.render_mock(mock_ir)
                current_tokens = estimator.estimate_messages(rendered)
            else:
                current_tokens = _estimate_from_data(new_items)

            if current_tokens <= target_budget:
                break

            largest_item, largest_key, largest_len = None, None, 0
            for item in new_items:
                if item.section == ContextSection.ARTIFACTS and item.projection:
                    for k, v in item.projection.data.items():
                        if k.lower() in _VERBOSE_FIELDS and isinstance(v, str) and len(v) > largest_len:
                            largest_len = len(v)
                            largest_item = item
                            largest_key = k

            if not largest_item:
                break

            new_len = int(largest_len * 0.8)
            new_data = dict(largest_item.projection.data)
            new_data[largest_key] = new_data[largest_key][:new_len] + "..."
            idx = new_items.index(largest_item)
            new_proj = replace(largest_item.projection, data=new_data)
            new_items[idx] = replace(largest_item, projection=new_proj)
            metrics["fields_compressed"] = metrics.get("fields_compressed", 0) + 1

        return replace(ir, items=tuple(new_items)), metrics


def _estimate_from_data(items: list) -> int:
    """Rough token estimate from item content lengths."""
    total = 0
    for item in items:
        if item.content:
            total += len(item.content) // 4
        if item.projection and item.projection.data:
            total += len(str(item.projection.data)) // 4
    return total
