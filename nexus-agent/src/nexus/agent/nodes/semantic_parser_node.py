"""Semantic Parser Node — parses natural language to IntentIR with caching.

Takes the last user message, checks ParseCache first. On cache miss,
makes ONE LLM call to output list[IntentIR]. On cache hit, skips
the LLM entirely (~13s saved).

Returns a StatePatch-compatible IR stack update. No mutable state changes.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from nexus.agent.state import AgentState
from nexus.compiler.cache import get_parse_cache
from nexus.compiler.ir_models import IntentIR
from nexus.config.settings import get_settings
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.agent.nodes.semantic_parser")

_SEMANTIC_PROMPT = """You are a semantic intent parser. Your ONLY job is to extract user intents from their latest message as structured IntentIR objects.

Available intents: {intents}

Rules:
1. Identify ALL intents in the user's message.
2. For each intent, extract: action (verb), domain (subject area), and entities (parameters).
3. Assign a confidence score (0.0 to 1.0) for each intent.
4. If NO intent matches well, return a single intent with action="unknown" and low confidence.
5. Return a JSON array of intent objects.

Output format:
```json
[
  {{
    "action": "retrieve",
    "domain": "weather",
    "entities": {{"city": "Tokyo"}},
    "confidence": 0.95,
    "raw_query": "original text"
  }}
]
```"""


async def semantic_parser_node(
    state: AgentState,
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Parse the user's last message into IntentIR list with caching.

    1. Check ParseCache — if hit, return cached IntentIR (no LLM)
    2. If miss, make ONE LLM call to output list[IntentIR]
    3. Store in ParseCache for future hits
    4. Return IR stack update (immutable — no state mutation)
    """
    # Get user message
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
        return {}

    # Get available intents from registry for the prompt
    available_intents: list[str] = []
    try:
        from nexus.agent.registry.intent_registry import get_registry
        available_intents = get_registry().get_intents()
    except Exception:
        pass

    tools = state.get("available_tools", [])
    cache = get_parse_cache()

    # 1. Try cache
    cached = await cache.get(last_message, tools, model)
    if cached is not None and cached:
        logger.info("semantic_parser.cache_hit", intent_count=len(cached))
        intents = [IntentIR(**i) for i in cached]
        return _build_return(intents, cached=True)

    # 2. LLM call (cache miss)
    settings = get_settings().agent
    prompt = _SEMANTIC_PROMPT.format(
        intents=", ".join(available_intents[:20]) if available_intents else "(none available)",
    )

    cost_usd = 0.0
    total_tokens = 0

    try:
        response = await llm.complete(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": last_message},
            ],
            temperature=0,
            max_tokens=settings.extraction_max_tokens,
            response_format={"type": "json_object"},
        )

        if hasattr(response, "usage") and response.usage:
            total_tokens = getattr(response.usage, "total_tokens", 0) or 0
            cost_usd = getattr(response, "cost_usd", 0.0) or 0.0

        content = response.content or "[]"
        content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
        content = re.sub(r"\n```$", "", content)

        parsed = json.loads(content)
        if isinstance(parsed, dict):
            parsed = [parsed]

    except Exception as exc:
        logger.error("semantic_parser.llm_failed", error=str(exc))
        return _build_error(exc, total_tokens, cost_usd)

    # Validate and wrap
    if not parsed or not isinstance(parsed, list):
        parsed = [{"action": "unknown", "domain": "general", "entities": {}, "confidence": 0.0}]

    intents = []
    for p in parsed[:10]:  # cap at 10 intents
        try:
            intent = IntentIR(
                action=p.get("action", "unknown"),
                domain=p.get("domain", "general"),
                entities=p.get("entities", {}),
                confidence=float(p.get("confidence", 1.0)),
                raw_query=p.get("raw_query", last_message),
            )
            intents.append(intent)
        except Exception:
            continue

    if not intents:
        intents = [IntentIR(action="unknown", domain="general", confidence=0.0)]

    # 3. Store in cache
    await cache.set(last_message, tools, model, [i.model_dump() for i in intents])

    logger.info(
        "semantic_parser.complete",
        intent_count=len(intents),
        actions=[i.action for i in intents],
        cached=False,
    )

    return _build_return(intents, total_tokens=total_tokens, cost_usd=cost_usd)


def _build_return(
    intents: list[IntentIR],
    cached: bool = False,
    total_tokens: int = 0,
    cost_usd: float = 0.0,
) -> dict[str, Any]:
    """Build the return dict with StatePatch-compatible IR stack update."""
    ir_stack_update = {
        "intents": [i.model_dump() for i in intents],
        "goals": [],
        "operations": [],
        "execution_plan": [],
    }

    result: dict[str, Any] = {
        "_ir_stack": ir_stack_update,
        "_extraction_result": {
            "intent": intents[0].action if len(intents) == 1 else [i.action for i in intents],
            "entities": intents[0].entities if intents else {},
            "confidence": intents[0].confidence if intents else 0.0,
        },
    }

    if total_tokens:
        result["_total_tokens"] = total_tokens
        result["_cost_breakdown"] = {"semantic_parser": cost_usd}
        result["total_cost_usd"] = cost_usd

    return result


def _build_error(
    exc: Exception,
    total_tokens: int = 0,
    cost_usd: float = 0.0,
) -> dict[str, Any]:
    """Build error return when LLM call fails."""
    result = _build_return(
        [IntentIR(action="extraction_error", domain="general", confidence=0.0)],
        total_tokens=total_tokens,
        cost_usd=cost_usd,
    )
    result["errors"] = [f"SemanticParser: LLM call failed — {exc}"]
    return result
