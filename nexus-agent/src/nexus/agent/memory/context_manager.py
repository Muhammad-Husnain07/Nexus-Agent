"""
Intelligent Context Manager — controls what data reaches the LLM at each
step to keep latency low, token costs down, and focus high.

Strategies
==========
1. **Sliding Window + Summarization** — Keep last N messages in full;
   compress older history into a compact summary via cheap LLM call or
   heuristic concatenation.

2. **Tool Result Pruning** — Large JSON blobs from tool APIs are truncated
   to ``max_chars`` for the LLM context.  Full results remain in
   ``working_memory`` for internal logic.

3. **Relevance Filtering** — Before planning, filter ``available_tools``
   to only those relevant to the current intent, using keyword overlap
   (or embedding similarity if available).

Usage::

    manager = ContextManager(llm=llm_client)
    compact = await manager.compress_history(messages)
    truncated = manager.truncate_tool_result(large_json, max_chars=500)
    relevant = manager.filter_relevant_tools(intent, all_tools, top_k=5)
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.agent.memory.context_manager")

_SUMMARY_PROMPT = """Summarize the following conversation turns in 2-3 sentences.
Focus on: what the user asked for, what data was retrieved, and any
user preferences expressed.

Conversation:
{text}

Summary:"""


# ============================================================================
# Sliding Window + Summarization
# ============================================================================


async def compress_history(
    messages: list[Any],
    llm: LLMClient | None = None,
    model: str | None = None,
    max_full: int = 5,
) -> list[dict[str, Any]]:
    """Keep last ``max_full`` messages in full detail; summarize everything older.

    Two-stage compression:
    1. **LLM path** (if ``llm`` provided): call a cheap model to produce
       a 2-3 sentence summary of the older turns.
    2. **Heuristic path** (fallback): concatenate older messages into a
       single compact ``system``-role entry with length limit.

    Args:
        messages: Full message history (list of dict or MessageEntry).
        llm: LLM client for summarization (optional).
        model: Model name for the summary call.
        max_full: Number of recent messages to keep in full detail.

    Returns:
        Compressed message list ready for LLM context injection.
    """
    if len(messages) <= max_full:
        return _to_dicts(messages)

    recent = messages[-max_full:]
    to_compress = messages[:-max_full]

    summary_text = ""
    if llm is not None and model is not None:
        summary_text = await _llm_summarize(to_compress, llm, model)
    else:
        summary_text = _heuristic_summarize(to_compress)

    compressed = []
    if summary_text:
        compressed.append({
            "role": "system",
            "content": f"[Previous conversation summary]: {summary_text}",
            "_milestone": True,
        })
    compressed.extend(_to_dicts(recent))

    logger.info(
        "context_manager.compress_history",
        original=len(messages),
        compressed=len(compressed),
        method="llm" if llm else "heuristic",
    )
    return compressed


async def _llm_summarize(
    messages: list[Any],
    llm: LLMClient,
    model: str,
) -> str:
    """Cheap LLM call to summarize older conversation turns."""
    text = _messages_to_text(messages)
    if not text.strip():
        return ""

    prompt = _SUMMARY_PROMPT.format(text=text[:2000])

    try:
        response = await llm.complete(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=256,
        )
        return (response.content or "").strip()
    except Exception as exc:
        logger.warning("context_manager.summarize_failed", error=str(exc))
        return _heuristic_summarize(messages)


def _heuristic_summarize(messages: list[Any]) -> str:
    """Fallback summarization — concatenate roles + truncated content."""
    parts = []
    for m in messages[-10:]:  # Only last 10 of the old section
        role = getattr(m, "role", m.get("role", "?"))
        content = getattr(m, "content", m.get("content", ""))
        if isinstance(content, str):
            parts.append(f"[{role}]: {content[:150]}")
    return "; ".join(parts[-5:])  # Keep only the last 5 entries


def _messages_to_text(messages: list[Any]) -> str:
    """Convert message list to plain text for summarization."""
    lines = []
    for m in messages[-15:]:  # Limit to last 15
        role = getattr(m, "role", m.get("role", "?"))
        content = getattr(m, "content", m.get("content", ""))
        if isinstance(content, str):
            lines.append(f"{role}: {content[:300]}")
    return "\n".join(lines)


def _to_dicts(messages: list[Any]) -> list[dict[str, Any]]:
    """Normalize messages to plain dicts (handles MessageEntry + dict)."""
    result = []
    for m in messages:
        if hasattr(m, "model_dump"):
            d = m.model_dump()
            result.append({
                "role": d.get("role", "user"),
                "content": d.get("content", ""),
                "_milestone": d.get("milestone", False),
            })
        elif isinstance(m, dict):
            result.append(m)
        else:
            result.append({"role": "user", "content": str(m)})
    return result


# ============================================================================
# Tool Result Pruning
# ============================================================================


def truncate_tool_result(
    result: Any,
    max_chars: int = 500,
) -> str:
    """Truncate a tool result to ``max_chars`` while hinting at the structure.

    The full result remains in ``working_memory`` for internal logic.
    This function produces the string that goes into the LLM prompt.

    Args:
        result: Raw tool output (dict, list, str, or None).
        max_chars: Max characters to include in the truncated version.

    Returns:
        Truncated JSON string, or ``"null"`` / ``"[]"`` for None/empty.
    """
    if result is None:
        return "null"
    if isinstance(result, str):
        result_str = result
    else:
        try:
            result_str = json.dumps(result, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            result_str = str(result)

    if len(result_str) <= max_chars:
        return result_str

    # Truncate with structure hint
    truncated = result_str[:max_chars]
    return truncated + f"...[truncated; full size: {len(result_str)} chars]"


# ============================================================================
# Relevance Filtering
# ============================================================================


def filter_relevant_tools(
    intent: str,
    tools: list[dict[str, Any]],
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Filter ``available_tools`` to only those relevant to the current intent.

    Uses simple keyword overlap scoring:
    1. Tokenize the intent query into words.
    2. For each tool, score by how many intent words appear in the tool's
       ``name``, ``description``, and ``purpose`` fields.
    3. Return the top-K scoring tools (minimum score > 0).

    When a vector DB / embedding model is available, this can be upgraded
    to semantic similarity.

    Args:
        intent: The parsed user intent (primary_goal or raw query).
        tools: All available tools.
        top_k: Max number of tools to return.

    Returns:
        Filtered tool list, sorted by relevance descending.
    """
    if not intent or not tools:
        return tools

    query_words = set(re.findall(r"[a-zA-Z_]\w+", intent.lower()))

    scored: list[tuple[float, dict[str, Any]]] = []
    for t in tools:
        text = " ".join([
            t.get("name", ""),
            t.get("description", ""),
            t.get("purpose", ""),
            " ".join(t.get("tags", [])),
            t.get("category", ""),
        ]).lower()

        # Count word overlap
        overlap = sum(1 for w in query_words if w in text)

        # Boost exact tool name matches
        name = t.get("name", "").lower()
        if name and name in intent.lower():
            overlap += 3

        # Boost purpose matches (higher weight)
        purpose = t.get("purpose", "").lower()
        if purpose and any(w in purpose for w in query_words if len(w) > 3):
            overlap += 2

        if overlap > 0:
            scored.append((overlap, t))

    scored.sort(key=lambda x: -x[0])
    result = [t for _, t in scored[:top_k]]

    # Fallback: if nothing matched, return all tools
    if not result:
        return tools[:top_k]

    return result
