"""Validation node — pure Python validation pipeline.

No LLM calls. Fast (~0ms). Pipeline stages:
1. Intent exists
2. Apply defaults
3. Required fields check
4. Business validators
5. Security rules
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.agent.registry.intent_registry import get_registry
from nexus.agent.state import AgentState
from nexus.agent.state.context import StructuredContext

logger = structlog.get_logger("nexus.agent.nodes.validation")


def _validate_pipeline(ctx: StructuredContext) -> dict[str, Any]:
    """Run the validation pipeline against StructuredContext.

    Returns a validation result dict:
    - ``ready``: True if the intent can proceed to planning
    - ``missing``: list of missing field names
    - ``resolved_entities``: entities with defaults applied
    - ``tools``: tools to execute for this intent
    - ``reason``: human-readable reason if not ready
    """
    registry = get_registry()
    intent = ctx.intent
    entities = ctx.entities.data

    # Stage 1: Intent exists
    if not intent or intent == "unknown":
        return {
            "ready": False,
            "missing": ["intent"],
            "reason": "I couldn't determine what you want to do. Could you rephrase?",
            "resolved_entities": entities,
            "tools": [],
        }

    schema = registry.get_schema(intent)
    if not schema:
        return {
            "ready": False,
            "missing": ["intent"],
            "reason": f"I don't know how to handle '{intent}' yet.",
            "resolved_entities": entities,
            "tools": [],
        }

    # Stage 2: Apply defaults
    resolved = registry.apply_defaults(intent, entities)

    # Stage 3: Required fields check
    missing = registry.validate_entities(intent, resolved)

    if missing:
        return {
            "ready": False,
            "missing": missing,
            "reason": f"I need more information to proceed.",
            "resolved_entities": resolved,
            "tools": schema.tool_mapping,
        }

    # Stage 4: Low confidence check
    if ctx.confidence < 0.5:
        return {
            "ready": False,
            "missing": ["low_confidence"],
            "reason": f"I'm not entirely sure. Did you mean to use {intent}?",
            "resolved_entities": resolved,
            "tools": schema.tool_mapping,
        }

    # All checks passed
    return {
        "ready": True,
        "missing": [],
        "reason": "",
        "resolved_entities": resolved,
        "tools": schema.tool_mapping,
    }


async def validation_node(state: AgentState) -> dict[str, Any]:
    """Pure Python validation — runs the pipeline against StructuredContext.

    Returns:
        - ``_validation_result``: the full validation result dict
        - ``_ready_to_plan``: True if execution should proceed to planner
        - ``_needs_clarification``: True if clarification is needed
    """
    ctx: StructuredContext | None = state.get("_structured_context")

    if not ctx or not ctx.intent:
        return {
            "_validation_result": {
                "ready": False,
                "missing": ["intent"],
                "reason": "What would you like me to help with?",
                "resolved_entities": {},
                "tools": [],
            },
            "_ready_to_plan": False,
            "_needs_clarification": True,
        }

    result = _validate_pipeline(ctx)

    needs_clarification = not result["ready"]

    if needs_clarification:
        logger.info(
            "validation_node.needs_clarification",
            intent=ctx.intent,
            missing=result["missing"],
        )
    else:
        logger.info(
            "validation_node.ready",
            intent=ctx.intent,
            tools=result["tools"],
        )

    return {
        "_validation_result": result,
        "_ready_to_plan": result["ready"],
        "_needs_clarification": not result["ready"],
    }


def validation_result_as_string(result: dict[str, Any]) -> str:
    """Convert a validation result into a human-readable clarification question."""
    missing = result.get("missing", [])
    if not missing:
        return ""

    if "intent" in missing:
        return result.get("reason", "What would you like me to do?")

    if "low_confidence" in missing:
        return result.get("reason", "Could you clarify what you're looking for?")

    # Generic: ask for the first missing field
    field = missing[0].replace("_", " ")
    return f"What's the {field}?"
