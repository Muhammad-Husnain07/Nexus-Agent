"""Extraction node — LLM ONLY extracts intent + entities. No validation."""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from nexus.agent.prompts import prompt_manager
from nexus.agent.registry.intent_registry import get_registry
from nexus.agent.state import AgentState
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
    """
    # Get the last user message
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

    # Get registered intents from the registry
    registry = get_registry()
    available_intents = registry.get_intents()

    # Build intent details with parameter names (keep compact for token budget)
    intent_details_lines = []
    for intent_name in available_intents:
        schema = registry.get_schema(intent_name)
        if schema:
            all_params = schema.required_fields + schema.optional_fields
            intent_details_lines.append(
                f"  - {intent_name}: params={','.join(all_params)}" if all_params else f"  - {intent_name}: params=none"
            )
    intent_details = "\n".join(intent_details_lines[:20]) if intent_details_lines else "(none)"

    # Render extraction prompt
    system_prompt = prompt_manager.render(
        "extraction",
        version="1.0",
        intents=", ".join(available_intents[:20]) if available_intents else "(none available)",
        intent_details=intent_details,
    )

    response = await llm.complete(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": last_message},
        ],
        temperature=0,
        max_tokens=512,
        response_format={"type": "json_object"},
    )

    content = response.content or "{}"
    content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
    content = re.sub(r"\n```$", "", content)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("extraction.parse_failed", content=content[:200])
        # Fallback: simple heuristic extraction from the raw message
        q_lower = last_message.lower()
        # Check for common tool keywords
        for intent_name in available_intents:
            keywords = intent_name.replace("_", " ").lower()
            if keywords in q_lower:
                parsed = {"intent": intent_name, "entities": {}, "confidence": 0.6}
                break
        else:
            parsed = {"intent": "unknown", "entities": {}, "confidence": 0.0}

    intent = parsed.get("intent", "unknown")
    entities = parsed.get("entities", {})
    confidence = float(parsed.get("confidence", 0.0))
    entity_confidence = parsed.get("entity_confidence", {})

    logger.info(
        "extraction_node.complete",
        intent=intent,
        confidence=confidence,
        entity_count=len(entities),
    )

    return {
        "_extraction_result": {
            "intent": intent,
            "entities": entities,
            "confidence": confidence,
            "entity_confidence": entity_confidence,
        }
    }
