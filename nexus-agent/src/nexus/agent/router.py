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

_CLASSIFIER_PROMPT = """You are a query classifier. Given a user message and available tools, determine the query type.

Types:
- single_tool: One clear tool request
- independent_multi: Multiple requests that don't depend on each other's output
- dependent_multi: Multiple requests where one tool's output feeds another
- conversational: Follow-up question with pronoun references ("it", "that", "his", "her", "their")
- no_tool: Greeting, meta question about the agent, memory query

<examples>
User: Tell me a joke
Tools: tool_a (returns a joke)
Type: single_tool
{"type": "single_tool", "tools": ["tool_a"], "reasoning": "Single clear tool request"}

User: What's the weather in SomeCity and tell me a joke
Tools: tool_b (geocode city), tool_c (get weather by coords), tool_a (returns a joke)
Analysis: tool_c needs coordinates from tool_b (dependent). tool_a is independent.
Type: dependent_multi
{"type": "dependent_multi", "tools": ["tool_b", "tool_c", "tool_a"], "dependencies": [["tool_b", "tool_c"]], "reasoning": "Weather needs geocoding first, joke is independent"}

User: What's the age of John and what's the Bitcoin price
Tools: tool_d (predict age from name), tool_e (get crypto price)
Analysis: Neither tool depends on the other's output.
Type: independent_multi
{"type": "independent_multi", "tools": ["tool_d", "tool_e"], "reasoning": "Age and crypto price are independent"}

User: And his nationality?
Tools: tool_f (predict nationality from name)
Analysis: "his" refers to a person from previous context.
Type: conversational
{"type": "conversational", "tools": ["tool_f"], "reasoning": "Follow-up with pronoun reference"}

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

# Conjunction markers suggesting multiple intents
_CONJUNCTIONS = {"and", "or", "also", "plus", "then", "too", "beside", "additionally"}

# Module-level cached weighted keyword index
# keyword → list of (tool_name, weight) pairs
_keyword_index: dict[str, list[tuple[str, float]]] = {}
_keyword_index_key: object = None


def _tokenize_query(text: str) -> list[str]:
    """Tokenize a user query: lowercase, strip punctuation, split, remove stop words."""
    import re
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = text.split()
    stop = {"a", "an", "the", "is", "it", "of", "in", "on", "for", "to", "with",
            "and", "or", "but", "not", "use", "when", "about", "that", "this",
            "from", "as", "at", "by", "be", "are", "was", "were", "been",
            "have", "has", "had", "do", "does", "did", "will", "would",
            "can", "could", "should", "may", "might", "shall", "need"}
    return [t for t in tokens if t not in stop and len(t) > 1]


def _rebuild_keyword_index(available_tools: list[dict[str, Any]]) -> None:
    """Build the weighted keyword index from precomputed tool keywords.

    Falls back to name-splitting for tools without precomputed keywords.
    """
    global _keyword_index, _keyword_index_key
    index: dict[str, list[tuple[str, float]]] = {}
    skip = {"get", "search", "predict", "find", "list", "fetch", "create", "update", "delete", "patch", "echo"}

    for t in available_tools:
        name = t.get("name", "")
        if not name:
            continue
        name_lower = name.lower()

        # Weight 5.0: exact tool name
        index.setdefault(name_lower, []).append((name, 5.0))

        # Use precomputed keywords from DB if available (weight 1.0 each)
        precomputed: list[str] | None = t.get("keywords")
        if precomputed:
            for kw in precomputed:
                index.setdefault(kw.lower(), []).append((name, 1.0))
        else:
            # Fallback: split name on underscore
            for part in name_lower.split("_"):
                if part not in skip and len(part) > 2:
                    index.setdefault(part, []).append((name, 1.0))

        # Tags (weight 0.8)
        for tag in (t.get("tags") or []):
            if isinstance(tag, str) and len(tag) > 2:
                index.setdefault(tag.lower(), []).append((name, 0.8))

        # Aliases (weight 1.5 — more specific than keywords)
        for alias in (t.get("aliases") or []):
            if isinstance(alias, str) and len(alias) > 2:
                index.setdefault(alias.lower(), []).append((name, 1.5))

    _keyword_index = index
    _keyword_index_key = id(available_tools)


def _get_keyword_index(available_tools: list[dict[str, Any]]) -> dict[str, list[tuple[str, float]]]:
    """Return the cached keyword index, rebuilding if tools changed."""
    global _keyword_index, _keyword_index_key
    if _keyword_index_key != id(available_tools) or not _keyword_index:
        _rebuild_keyword_index(available_tools)
    return _keyword_index


def _reset_keyword_index() -> None:
    """Force the keyword index to rebuild on next access (called by runner on cache refresh)."""
    global _keyword_index_key
    _keyword_index_key = None


def _match_tools(query: str, available_tools: list[dict[str, Any]]) -> set[str]:
    """Tokenize the user query and score tools against the cached keyword index.

    Returns a set of matched tool names with total weight >= 1.0.
    """
    if not available_tools:
        return set()
    tokens = _tokenize_query(query)
    if not tokens:
        return set()
    index = _get_keyword_index(available_tools)
    scores: dict[str, float] = {}
    for token in tokens:
        for tool_name, weight in index.get(token, []):
            scores[tool_name] = scores.get(tool_name, 0) + weight
    return {t for t, s in scores.items() if s >= 1.0}


def _heuristic_classify(
    query: str,
    history: list[dict[str, Any]],
    tool_names: list[str],
    available_tools: list[dict[str, Any]] | None = None,
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
        tname.lower().replace("_", " ") in q for tname in tool_names
    ):
        return QueryType.CONVERSATIONAL

    # 3. Match query against cached weighted keyword index
    matched_tools = _match_tools(q, available_tools or [])

    # 5. No tool matched → likely conversational or no_tool
    if not matched_tools:
        return QueryType.CONVERSATIONAL if has_prior_assistant else None

    # 6. Single tool
    if len(matched_tools) == 1:
        return QueryType.SINGLE_TOOL

    # 7. Multiple tools — check for conjunctions to confirm multi-intent
    words = set(q.split())
    has_conjunction = bool(words & _CONJUNCTIONS)

    # 8. Check for I/O dependencies via schema analysis
    has_dependency = _has_schema_dependency(matched_tools, available_tools or [])

    if has_dependency:
        return QueryType.DEPENDENT_MULTI

    if has_conjunction or len(matched_tools) >= 2:
        return QueryType.INDEPENDENT_MULTI

    return None  # Ambiguous — fall through to LLM


def _has_schema_dependency(matched_tools: set[str], all_tools: list[dict[str, Any]]) -> bool:
    """Check if any matched tool's required input is another's output (schema-driven)."""
    signatures: dict[str, tuple[set[str], set[str]]] = {}
    for t in all_tools:
        name = t.get("name", "")
        inp = t.get("input_schema", {})
        out = t.get("output_schema", {})
        required = set(inp.get("required", [])) if isinstance(inp, dict) else set()
        outputs = set(out.get("properties", {}).keys()) if isinstance(out, dict) else set()
        signatures[name] = (required, outputs)

    all_outputs: set[str] = set()
    for name in matched_tools:
        _, outs = signatures.get(name, (set(), set()))
        all_outputs |= outs

    for name in matched_tools:
        reqs, _ = signatures.get(name, (set(), set()))
        if reqs & all_outputs:
            return True
    return False


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
    """LangGraph node: classify the user's latest message and set ``_query_type``."""
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

    forced = state.get("_force_query_type")
    if forced:
        logger.info("router.forced_type", qtype=forced, query=last_user[:50])
        return {"_query_type": forced}

    available_tools: list[dict[str, Any]] = state.get("available_tools") or []
    tool_names = [t.get("name", "") for t in available_tools if t.get("name")]

    qtype = await classify_query(
        query=last_user,
        history=messages,
        tool_names=tool_names,
        available_tools=available_tools,
        llm=llm,
        model=model,
    )

    result: dict[str, Any] = {"_query_type": qtype.value}

    # For multi-tool types, pre-select preferred tools using weighted index
    if qtype in (QueryType.INDEPENDENT_MULTI, QueryType.DEPENDENT_MULTI):
        matched = _match_tools(last_user.lower(), available_tools)
        if matched:
            result["_preferred_tools"] = list(matched)

    return result


async def classify_query(
    query: str,
    history: list[dict[str, Any]] | None = None,
    tool_names: list[str] | None = None,
    available_tools: list[dict[str, Any]] | None = None,
    llm: LLMClient | None = None,
    model: str | None = None,
) -> QueryType:
    """Classify a user query into a ``QueryType``.

    Two-stage pipeline:
    1. **Heuristic** (deterministic, ~0ms) — catches greetings, single-tool,
       conversational follow-ups, and obvious multi-tool queries.
    2. **LLM** (compact few-shot, ~500ms) — only for ambiguous cases the
       heuristic can't confidently classify.
    """
    # Stage 1: Heuristic
    tool_names_list = tool_names or []
    heuristic_result = _heuristic_classify(query, history or [], tool_names_list, available_tools)

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



