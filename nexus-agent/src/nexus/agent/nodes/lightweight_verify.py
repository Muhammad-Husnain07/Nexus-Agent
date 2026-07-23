"""lightweight_verify — single LLM critique for medium-confidence intents.

Replaces the old ``self_consistency`` node that ran k=3-5 parallel samples
and voted.  This node does a single fast critique call — ~1/3 the latency
with comparable reliability.

Routes:
- "proceed": intent is clear enough → tool_subgraph
- "clarify": ambiguous or missing info → gather_requirements
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from nexus.agent.state import AgentState
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.agent.nodes.lightweight_verify")

_VERIFY_PROMPT = """You are a verification assistant. Review the user's request and the proposed intent analysis below.

User request: {query}

Proposed intent: {intent}

Your job: Determine if this intent analysis is correct, ambiguous, or wrong.

Return JSON:
{{"verdict": "correct" | "ambiguous" | "wrong", "reason": "brief explanation"}}

If "ambiguous": what's needed to clarify?
If "wrong": what should the intent be instead?
"""


async def lightweight_verify(
    state: AgentState,
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Run a single fast critique on the intent analysis.

    For medium-confidence queries (0.5–0.7) from ``understand_intent``,
    this node decides whether to proceed or ask for clarification.

    Returns:
        Dict with ``_routing_decision`` ("proceed" or "clarify") and
        optionally a ``final_response`` if clarification is needed.
    """
    intent: dict[str, Any] = state.get("intent_analysis") or {}
    messages: list = list(state.get("messages", []))
    last_user = ""
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            last_user = str(m.get("content", ""))
            break

    intent_text = intent.get("primary_goal", "unknown")
    query = last_user or ""

    if not query:
        logger.warning("lightweight_verify.no_query")
        return {"_routing_decision": "ask", "final_response": "I didn't catch that. Could you rephrase?"}

    prompt = _VERIFY_PROMPT.format(query=query[:500], intent=intent_text[:200])

    try:
        response = await llm.complete(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=256,
            response_format={"type": "json_object"},
        )
        content = response.content or ""
        if content.startswith("```"):
            import re
            content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
            content = re.sub(r"\n```$", "", content)
        parsed = json.loads(content)
        verdict = parsed.get("verdict", "ambiguous")
    except Exception:
        logger.warning("lightweight_verify.parse_failed", content=response.content if 'response' in dir() else "")
        verdict = "ambiguous"

    if verdict == "wrong":
        logger.info("lightweight_verify.wrong_intent", intent=intent_text)
        return {
            "_routing_decision": "clarify",
            "final_response": "I'm not confident I understood correctly. Could you rephrase your request?",
        }

    if verdict == "ambiguous":
        logger.info("lightweight_verify.ambiguous", intent=intent_text)
        missing = intent.get("missing_info_slots", [])
        if missing:
            slot_names = [s.get("name", "") if isinstance(s, dict) else str(s) for s in missing]
            return {
                "_routing_decision": "clarify",
                "final_response": f"I need a bit more information: {', '.join(slot_names[:3])}.",
            }
        return {
            "_routing_decision": "clarify",
            "final_response": "Could you clarify what you're looking for?",
        }

    logger.info("lightweight_verify.proceed", intent=intent_text)
    return {"_routing_decision": "proceed"}
