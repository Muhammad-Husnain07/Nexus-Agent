"""feedback_interrupt — interrupt for human feedback on intermediate results.

Extracted from the ``present_preview`` node so the interrupt logic can be
reused and tested independently.
"""

from __future__ import annotations

from typing import Any

import structlog
from langgraph.types import interrupt

logger = structlog.get_logger("nexus.agent.feedback_interrupt")


def interrupt_for_feedback(
    preview_data: dict[str, Any],
) -> dict[str, Any]:
    """Pause the graph for human feedback on an intermediate result.

    Calls ``langgraph.types.interrupt(preview_data)`` and returns the
    resumed decision dict.  The decision is expected to have the shape:

    .. code-block:: python

        {"action": "approve" | "edit" | "reject",
         "feedback": str | None}

    Args:
        preview_data: A dict with at least ``"type"``, ``"preview"``,
            and ``"options"`` — typically produced by the caller node.

    Returns:
        The decision dict provided by the external caller on resume.
    """
    logger.info(
        "feedback_interrupt.interrupt",
        preview_type=preview_data.get("type"),
        preview_length=len(str(preview_data.get("preview", ""))),
    )
    value: dict[str, Any] = interrupt(preview_data)
    action = value.get("action", "approve")
    result: dict[str, Any] = {
        "action": action,
        "feedback": value.get("feedback") if action in ("reject", "edit") else None,
    }
    if action == "edit" and "modifications" in value:
        result["modifications"] = value["modifications"]
    if action == "edit" and "edited_inputs" in value:
        result["edited_inputs"] = value["edited_inputs"]
    return result
