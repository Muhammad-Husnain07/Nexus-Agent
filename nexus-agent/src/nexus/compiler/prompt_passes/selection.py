"""SelectionPass — selects items from ContextIR based on ContextPolicy limits."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from nexus.compiler.context_ir import ContextIR, ContextItem, ContextSection
from nexus.compiler.prompt_passes import CompilerPass


class SelectionPass(CompilerPass):
    """Select a subset of context items that fit within policy limits.

    Keeps all SYSTEM_INSTRUCTIONS and USER_INTENT items, then appends
    up to ``max_artifacts`` artifact projections and up to
    ``max_history_turns`` history items.
    """

    name = "selection"
    requires: list[str] = []
    produces: list[str] = ["selected_items"]
    # Kwarg contract: the pipeline injects exactly these (no name dispatch)
    accepts: dict[str, str] = {"policy": "ContextPolicy"}

    def run(self, ir: ContextIR, metrics: dict[str, Any], **kwargs: Any) -> tuple[ContextIR, dict[str, Any]]:
        policy = kwargs.get("policy") or ir.policy
        artifacts = [i for i in ir.items if i.section == ContextSection.ARTIFACTS][: policy.max_artifacts]
        history = [i for i in ir.items if i.section == ContextSection.HISTORY][-policy.max_history_turns :]
        new_items = (
            [i for i in ir.items if i.section in (ContextSection.SYSTEM_INSTRUCTIONS, ContextSection.USER_INTENT)]
            + artifacts
            + history
        )
        metrics["selected_items"] = len(new_items)
        return replace(ir, items=tuple(new_items)), metrics
