"""Query classifier — two-stage query-type detection.

Two-stage classification:
1. **Heuristic** (~0ms): greeting keywords, single tool name, conjunctions,
   follow-up detection from conversation history.
2. **LLM** (~500ms): compact few-shot call for ambiguous/multi-tool queries
   to distinguish INDEPENDENT_MULTI from DEPENDENT_MULTI.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any

import structlog

from nexus.agent.state import AgentState
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.agent.router")


# ============================================================================
# Query Type Enum
# ============================================================================

class QueryType(str, Enum):
    """Classification of user query for optimized execution routing.

    Determines which graph path the query takes:
    - ``SINGLE_TOOL``: One clear tool invocation.  Bypass planner.
    - ``INDEPENDENT_MULTI``: Multiple tools, no dependencies between them.
      Execute in parallel via FanOut.
    - ``DEPENDENT_MULTI``: Multiple tools with output→input chains
      (e.g. geocode → weather).  Execute via DAG planner.
    - ``CONVERSATIONAL``: Follow-up question with pronoun references.
      Reuse or adapt prior plan.
    - ``NO_TOOL_NEEDED``: Greeting, meta question, memory query.
      Direct response, no tools.
    """
    SINGLE_TOOL = "single_tool"
    INDEPENDENT_MULTI = "independent_multi"
    DEPENDENT_MULTI = "dependent_multi"
    CONVERSATIONAL = "conversational"
    NO_TOOL_NEEDED = "no_tool"


# ============================================================================
# Few-Shot System Prompt
# ============================================================================

_CLASSIFIER_PROMPT = """You are a query classifier. Given a user message and a list of available tools, determine the query type.

Types:
- single_tool: One clear tool request
- independent_multi: Multiple requests that don't depend on each other's output
- dependent_multi: Multiple requests where one tool's output feeds another (e.g. geocoding → weather)
- conversational: Follow-up question with pronoun references ("it", "that", "his", "her", "their")
- no_tool: Greeting, meta question about the agent, memory query

<examples>
User: Tell me a joke
Tools: get_joke
Type: single_tool
{"type": "single_tool", "tools": ["get_joke"], "reasoning": "Single clear tool request"}

User: What's the weather in London and tell me a joke
Tools: get_geocoding, get_weather, get_joke
Analysis: get_weather needs coordinates from get_geocoding (dependent). get_joke is independent.
Type: dependent_multi
{"type": "dependent_multi", "tools": ["get_geocoding", "get_weather", "get_joke"], "dependencies": [["get_geocoding", "get_weather"]], "reasoning": "Weather needs geocoding first, joke is independent"}

User: What's the age of John and what's the Bitcoin price
Tools: predict_age, get_crypto_price
Analysis: Neither tool depends on the other's output.
Type: independent_multi
{"type": "independent_multi", "tools": ["predict_age", "get_crypto_price"], "reasoning": "Age and crypto price are independent"}

User: And his nationality?
Tools: predict_nationality
Analysis: "his" refers to a person from previous context.
Type: conversational
{"type": "conversational", "tools": ["predict_nationality"], "reasoning": "Follow-up with pronoun reference"}

User: Hi, how are you?
Type: no_tool
{"type": "no_tool", "reasoning": "Greeting"}

User: What tools do you have?
Tools: (all tools)
Type: no_tool
{"type": "no_tool", "reasoning": "Meta question about agent capabilities"}
</examples>

Return ONLY valid JSON. No explanation, no preamble.
The JSON must contain "type" and optionally "tools" and "dependencies" keys."""


# ============================================================================
# Heuristic Classification (Stage 1 — fast path)
# ============================================================================

# One-word greetings and common social phrases
_GREETINGS = frozenset({
    "hi", "hello", "hey", "howdy", "yo", "sup", "greetings", "good morning",
    "good afternoon", "good evening", "morning", "evening", "thanks", "thank you",
    "thanks!", "hello!", "hi!", "hey!", "goodbye", "bye", "bye!",
})

# Tool name patterns — normalized to match tool names
# Maps user intent patterns to likely tool names (soft match, not hardcoded)
_TOOL_PATTERNS = {
    "joke": "get_joke",
    "jokes": "get_joke",
    "funny": "get_joke",
    "weather": "get_weather",
    "temperature": "get_weather",
    "forecast": "get_weather",
    "geocode": "get_geocoding",
    "coordinates": "get_geocoding",
    "latitude": "get_geocoding",
    "age": "predict_age",
    "how old": "predict_age",
    "nationality": "predict_nationality",
    "where from": "predict_nationality",
    "bitcoin": "get_crypto_price",
    "crypto": "get_crypto_price",
    "price": "get_crypto_price",
    "pokemon": "get_pokemon",
    "pikachu": "get_pokemon",
    "charizard": "get_pokemon",
    "cat fact": "get_cat_fact",
    "cat": "get_cat_fact",
    "dog": "get_dog_image",
    "dog image": "get_dog_image",
    "puppy": "get_dog_image",
    "trivia": "get_trivia",
    "star wars": "get_starwars_character",
    "pok\u00e9mon": "get_pokemon",
}

# Conjunction markers suggesting multiple intents
_CONJUNCTIONS = {"and", "or", "also", "plus", "then", "too", "beside", "additionally"}


def _heuristic_classify(
    query: str,
    history: list[dict[str, Any]],
    tool_names: list[str],
) -> QueryType | None:
    """Fast heuristic classification — returns ``None`` if ambiguous.

    Rules (applied in order):
    1. Empty or one-word greetings → ``NO_TOOL_NEEDED``
    2. Short query with prior assistant response → ``CONVERSATIONAL``
    3. Single tool pattern match → ``SINGLE_TOOL``
    4. Multiple tool patterns + no dependencies → ``INDEPENDENT_MULTI``
    5. Multiple tool patterns + I/O dependency → ``DEPENDENT_MULTI``
    """
    q = query.lower().strip()
    if not q:
        return QueryType.NO_TOOL_NEEDED

    # 1. Greeting check
    if q in _GREETINGS or len(q.split()) <= 3 and q in _GREETINGS:
        return QueryType.NO_TOOL_NEEDED

    # 2. Conversational follow-up: short query + prior assistant response
    has_prior_assistant = any(
        isinstance(m, dict) and m.get("role") == "assistant"
        for m in (history or [])
    )
    if has_prior_assistant and len(q.split()) <= 8 and not any(
        p[0] in q for p in _TOOL_PATTERNS.items()
    ):
        return QueryType.CONVERSATIONAL

    # 3. Count tool patterns in query
    matched_tools: set[str] = set()
    for pattern, tool in _TOOL_PATTERNS.items():
        if pattern in q:
            matched_tools.add(tool)

    # Also match against actual tool names in the registry
    for tname in tool_names:
        normalized = tname.lower().replace("_", " ")
        if normalized in q:
            matched_tools.add(tname)

    # 4. No tool matched → likely conversational or no_tool
    if not matched_tools:
        return QueryType.CONVERSATIONAL if has_prior_assistant else None

    # 5. Single tool
    if len(matched_tools) == 1:
        return QueryType.SINGLE_TOOL

    # 6. Multiple tools — check for conjunctions to confirm multi-intent
    words = set(q.split())
    has_conjunction = bool(words & _CONJUNCTIONS)

    if not has_conjunction and len(matched_tools) >= 2:
        # May still be multi-intent with implied "and" (e.g. "weather tokyo bitcoin price")
        pass

    # Check for I/O dependencies between matched tools
    # (simple heuristic: tools that take lat/lon or id as input)
    dependent_pairs = {
        ("get_geocoding", "get_weather"),
        ("get_geocoding", "get_weather"),
        ("search_books", "get_book_details"),
    }
    tool_list = list(matched_tools)
    has_dependency = any(
        (a, b) in dependent_pairs
        for a in tool_list for b in tool_list if a != b
    )

    if has_dependency:
        return QueryType.DEPENDENT_MULTI

    if has_conjunction or len(matched_tools) >= 2:
        return QueryType.INDEPENDENT_MULTI

    return None  # Ambiguous — fall through to LLM


# ============================================================================
# LLM Classification (Stage 2 — for ambiguous cases)
# ============================================================================

async def _llm_classify(
    query: str,
    tool_names: list[str],
    llm: LLMClient,
    model: str,
) -> QueryType:
    """Use compact few-shot LLM call to classify ambiguous queries."""
    tools_str = ", ".join(tool_names) if tool_names else "(none)"

    prompt = (
        f"User: {query[:500]}\n"
        f"Tools: {tools_str}\n"
        f"Type and JSON:"
    )

    try:
        response = await llm.complete(
            model=model,
            messages=[
                {"role": "system", "content": _CLASSIFIER_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=256,
            response_format={"type": "json_object"},
        )
        content = response.content or ""
        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
            content = re.sub(r"\n```$", "", content)

        parsed = json.loads(content)
        raw_type = parsed.get("type", "")

        for qt in QueryType:
            if qt.value == raw_type:
                return qt

        logger.warning("router.unrecognized_llm_type", raw=raw_type)
        return QueryType.SINGLE_TOOL  # safe fallback

    except Exception as exc:
        logger.warning("router.llm_classify_failed", error=str(exc))
        return QueryType.SINGLE_TOOL  # safe fallback


# ============================================================================
# Public API
# ============================================================================

async def node_classify_query(
    state: AgentState,
    llm: LLMClient | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """LangGraph node: classify the user's latest message and set ``_query_type``.

    Reads the last user message from ``state["messages"]``, extracts tool
    names from ``state["available_tools"]``, runs classification, and
    stores the result in ``state["_query_type"]`` for routing.

    The classification result can be overridden by ``_force_query_type``
    (set by earlier routing logic for specific edge cases).

    Returns:
        Dict with ``_query_type`` (str) and optionally ``_preferred_tools``.
    """
    messages: list = list(state.get("messages", []))
    last_user = ""
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            last_user = str(m.get("content", ""))
            break
        if hasattr(m, "role") and getattr(m, "role") == "user":
            last_user = str(getattr(m, "content", ""))
            break

    if not last_user:
        return {"_query_type": QueryType.NO_TOOL_NEEDED.value}

    # Check for overrides set by prior routing
    forced = state.get("_force_query_type")
    if forced:
        logger.info("router.forced_type", qtype=forced, query=last_user[:50])
        return {"_query_type": forced}

    # Extract tool names from available tools
    tool_names = [
        t.get("name", "") for t in (state.get("available_tools") or [])
        if t.get("name")
    ]

    # Classify
    qtype = await classify_query(
        query=last_user,
        history=messages,
        tool_names=tool_names,
        llm=llm,
        model=model,
    )

    result: dict[str, Any] = {"_query_type": qtype.value}

    # For multi-tool types, optionally pre-select preferred tools
    if qtype in (QueryType.INDEPENDENT_MULTI, QueryType.DEPENDENT_MULTI):
        matched = set()
        q_lower = last_user.lower()
        for pattern, tool in _TOOL_PATTERNS.items():
            if pattern in q_lower:
                matched.add(tool)
        for tname in tool_names:
            if tname.lower().replace("_", " ") in q_lower:
                matched.add(tname)
        if matched:
            result["_preferred_tools"] = list(matched)

    return result


async def classify_query(
    query: str,
    history: list[dict[str, Any]] | None = None,
    tool_names: list[str] | None = None,
    llm: LLMClient | None = None,
    model: str | None = None,
) -> QueryType:
    """Classify a user query into a ``QueryType``.

    Two-stage pipeline:
    1. **Heuristic** (deterministic, ~0ms) — catches greetings, single-tool,
       conversational follow-ups, and obvious multi-tool queries.
    2. **LLM** (compact few-shot, ~500ms) — only for ambiguous cases the
       heuristic can't confidently classify.

    Args:
        query: The user's message text.
        history: Prior conversation messages (for conversational detection).
        tool_names: List of available tool names from the registry.
        llm: LLM client (required for Stage 2 fallback).
        model: Model name to use for Stage 2.

    Returns:
        A ``QueryType`` enum value.
    """
    # Stage 1: Heuristic
    tool_names_list = tool_names or []
    heuristic_result = _heuristic_classify(query, history or [], tool_names_list)

    if heuristic_result is not None:
        logger.info(
            "router.heuristic_classified",
            query=query[:50],
            qtype=heuristic_result.value,
        )
        return heuristic_result

    # Stage 2: LLM fallback
    if llm is not None and model is not None:
        llm_result = await _llm_classify(query, tool_names_list, llm, model)
        logger.info(
            "router.llm_classified",
            query=query[:50],
            qtype=llm_result.value,
        )
        return llm_result

    # Fallback
    logger.info("router.default_classified", query=query[:50])
    return QueryType.SINGLE_TOOL



