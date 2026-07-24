"""Clarification node — asks user for missing information, then ENDs.

The graph terminates after this node. The user's next message starts
a fresh extraction -> validation -> clarify/plan cycle.

Records what was asked so the next turn's merge can detect resolution.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.agent.nodes.validation_node import validation_result_as_string
from nexus.agent.state import AgentState

logger = structlog.get_logger("nexus.agent.nodes.clarification")


async def clarification_node(state: AgentState) -> dict[str, Any]:
    """Generate a clarification question and end the graph.

    Reads ``_validation_result`` to determine what's missing.
    Composes a natural question. Returns without continuing the graph.
    Records what was asked for next-turn context.
    """
    validation = state.get("_validation_result", {})

    question = validation_result_as_string(validation)

    if not question:
        question = "Could you provide more details?"

    missing = validation.get("missing", [])

    logger.info(
        "clarification_node.asked",
        question=question,
        missing=missing,
    )

    return {
        "final_response": question,
        "_routing_decision": "finalize",
        "_clarification_asked": {
            "missing": missing,
            "question": question,
        },
    }
