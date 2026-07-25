"""Extraction node — LLM ONLY extracts intent + entities. No validation.

Supports both single and multi-intent extraction. For multi-intent queries,
the LLM returns a list of intents and tool_names. The context merge node
handles both cases.

On LLM failure, returns a distinguishable ``extraction_error`` intent
(instead of reusing ``unknown`` for both system errors and genuine ambiguity).
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from nexus.agent.prompts import prompt_manager
from nexus.agent.registry.intent_registry import get_registry
from nexus.agent.state import AgentState
from nexus.config.settings import get_settings
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.agent.nodes.extraction")


async def extraction_node(
    state: AgentState,
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Extract intent and entities from the user's last message.

    Pure extraction — no validation, no correction detection, no planning.
    Returns ONLY the structured context update.

    Uses prompt v2 for multi-intent queries, v1 for single-intent.
    On failure, records cost if available and returns ``extraction_error``
    intent so downstream nodes can distinguish system errors from ambiguity.
    """
    messages = state.get("messages", [])
    last_message = ""
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            last_message = str(m.get("content", ""))
            break
        if hasattr(m, "role") and getattr(m, "role") == "user":
            last_message = str(getattr(m, "content", ""))
            break

    if not last_message:
        return {"_extraction_result": {"intent": None, "entities": {}, "confidence": 0.0}}

    registry = get_registry()
    available_intents = registry.get_intents()

    # Build a slim intent view for the extraction prompt.
    # Extraction only needs to know a tool exists and roughly what it does —
    # parameter details are for the planner, not extraction.
    intent_details_lines = []
    for intent_name in available_intents:
        schema = registry.get_schema(intent_name)
        if schema:
            desc = (schema.description or intent_name)[:80]
            intent_details_lines.append(f"  - {intent_name}: {desc}")
    _extraction_settings = get_settings().agent
    max_intents = _extraction_settings.max_intent_display
    intent_details = "\n".join(intent_details_lines[:max_intents]) if intent_details_lines else "(none)"

    # Determine if multi-intent
    qtype = state.get("_query_type", "single_tool")
    is_multi = qtype in ("independent_multi", "dependent_multi")
    prompt_version = "2.0" if is_multi else "1.0"

    system_prompt = prompt_manager.render(
        "extraction",
        version=prompt_version,
        intents=", ".join(available_intents[:max_intents]) if available_intents else "(none available)",
        intent_details=intent_details,
    )

    # Make the LLM call — the client always returns an LLMResponse with cost data,
    # even on transient failures (timeout, API error).
    response = await llm.complete(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": last_message},
        ],
        temperature=_extraction_settings.extraction_temperature,
        max_tokens=_extraction_settings.extraction_max_tokens,
        response_format={"type": "json_object"},
    )

    # Always capture cost/tokens — LLMResponse has them even on failure
    total_tokens = getattr(response.usage, "total_tokens", 0) if response.usage else 0
    cost_usd = getattr(response, "cost_usd", 0.0) or 0.0

    content = response.content or "{}"
    content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
    content = re.sub(r"\n```$", "", content)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("extraction.parse_failed", content=content[:200])
        q_lower = last_message.lower()
        fallback_conf = get_settings().agent.fallback_confidence
        for intent_name in available_intents:
            keywords = intent_name.replace("_", " ").lower()
            if keywords in q_lower:
                parsed = {"intent": intent_name, "entities": {}, "confidence": fallback_conf}
                break
        else:
            parsed = {"intent": "unknown", "entities": {}, "confidence": 0.0}

    # Check if the LLM call itself failed (empty content + zero tokens = provider error)
    if not content or content in ("{}", ""):
        logger.error("extraction_node.llm_failed", content=content[:200], cost=cost_usd)
        return {
            "_extraction_result": {
                "intent": "extraction_error",
                "entities": {},
                "tool_names": [],
                "business_requirements": {},
                "confidence": 0.0,
                "entity_confidence": {},
            },
            "errors": ["ExtractionNode: LLM returned empty response"],
            "_total_tokens": total_tokens,
            "_cost_breakdown": {"extraction": cost_usd},
            "total_cost_usd": cost_usd,
        }

    intent = parsed.get("intent", "unknown")
    entities = parsed.get("entities", {})
    tool_names = parsed.get("tool_names", [])
    business_requirements = parsed.get("business_requirements", {})
    confidence = float(parsed.get("confidence", 0.0))
    entity_confidence = parsed.get("entity_confidence", {})

    logger.info(
        "extraction_node.complete",
        intent=intent if isinstance(intent, str) else f"multi({len(intent)})",
        confidence=confidence,
        entity_count=len(entities),
        business_requirement_count=len(business_requirements),
    )

    return {
        "_extraction_result": {
            "intent": intent,
            "entities": entities,
            "tool_names": tool_names,
            "business_requirements": business_requirements,
            "confidence": confidence,
            "entity_confidence": entity_confidence,
        },
        "_total_tokens": total_tokens,
        "_cost_breakdown": {"extraction": cost_usd},
        "total_cost_usd": cost_usd,
    }
