"""Clarification node — asks user for missing information, then ENDs.

The graph terminates after this node. The user's next message starts
a fresh extraction -> validation -> clarify/plan cycle.

Records what was asked so the next turn's merge can detect resolution.
Also appends the question to the message history and persists to memory.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from nexus.agent.nodes.memory_helper_node import persist_after_response
from nexus.agent.nodes.validation_node import validation_result_as_string
from nexus.agent.state import AgentState

logger = structlog.get_logger("nexus.agent.nodes.clarification")


async def clarification_node(state: AgentState) -> dict[str, Any]:
    """Generate a clarification question and end the graph.

    Reads ``_validation_result`` to determine what's missing.
    Composes a natural question. Returns without continuing the graph.
    Records what was asked for next-turn context.
    Appends the question to messages so the conversation history
    is complete for the next turn. Also persists to working memory.
    """
    validation = state.get("_validation_result", {})

    question = validation_result_as_string(validation)

    if not question:
        # Try to build a specific question from the router's preferred tools signal
        preferred = state.get("_preferred_tools", [])
        if preferred:
            names = [p.replace("_", " ").title() for p in preferred]
            if names:
                unique = list(dict.fromkeys(names))[:5]  # dedup, max 5
                if len(unique) == 1:
                    question = f"It looks like you're asking about “{unique[0]}” — could you provide more details?"
                else:
                    items = "; ".join(unique)
                    question = f"I can help with several things: {items}. Which one should I start with?"
        if not question:
            question = "Could you provide more details?"

    missing = validation.get("missing", [])

    logger.info(
        "clarification_node.asked",
        question=question,
        missing=missing,
    )

    # Persist to memory (fire-and-forget — no session_factory needed for basic path)
    working_memory_update = await persist_after_response(state, question)

    return {
        "final_response": question,
        "_routing_decision": "finalize",
        "response_type": "clarification",
        "_clarification_asked": {
            "missing": missing,
            "question": question,
        },
        "messages": [
            {
                "role": "assistant",
                "content": question,
                "id": str(uuid.uuid4()),
            }
        ],
        "working_memory": working_memory_update,
    }
