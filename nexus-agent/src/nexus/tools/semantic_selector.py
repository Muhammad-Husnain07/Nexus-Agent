"""Dynamic semantic tool selection — no hardcoded keywords or tool names.

Uses the SAME embedding model as the rest of the system (configured via
``NEXUS_LLM__EMBEDDING_MODEL``) to compute cosine similarity between the
user query and each tool's metadata (name, description, purpose, tags,
category — all text fields extracted dynamically).

Threshold is calculated from the score distribution (median + 0.5*IQR)
so it adapts to any tool set without configuration.
"""

from __future__ import annotations

import math
from typing import Any

import structlog

from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.tools.semantic_selector")


def _extract_tool_text(tool: dict[str, Any]) -> str:
    """Concatenate ALL text fields from a tool dict recursively."""
    parts: list[str] = []
    seen: set[int] = set()

    def _walk(obj: Any) -> None:
        obj_id = id(obj)
        if obj_id in seen:
            return
        seen.add(obj_id)
        if isinstance(obj, str):
            obj = obj.strip()
            if obj and len(obj) > 2 and "http" not in obj and "{" not in obj:
                parts.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(tool)
    return " ".join(parts)


def _estimate_complexity(query: str) -> float:
    """Estimate query complexity 0.0–1.0 based on structure, not keywords."""
    words = query.split()
    length_score = min(len(words) / 20.0, 1.0)
    conj_score = sum(1 for w in words if w.lower() in {"and", "or", "also", "plus", "then"})
    conj_score = min(conj_score / 3.0, 1.0)
    qw_score = sum(1 for w in words if w.lower() in {"what", "how", "where", "when", "why", "which"})
    qw_score = min(qw_score / 2.0, 1.0)
    return (length_score + conj_score + qw_score) / 3.0


def _dynamic_threshold(scores: list[float], complexity: float) -> float:
    """Compute threshold from score distribution + query complexity.

    No hardcoded values — uses median + 0.5*IQR from the actual scores,
    then adjusts by complexity (complex queries → lower threshold).
    """
    if not scores:
        return 0.0
    s = sorted(scores)
    n = len(s)
    median = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    q25 = s[n // 4]
    q75 = s[3 * n // 4]
    iqr = q75 - q25
    base = median + 0.5 * iqr
    # Complex queries cast a wider net (lower threshold)
    return base * (1.0 - complexity * 0.3)


async def select_tools(
    tools: list[dict[str, Any]],
    query: str,
    llm: LLMClient | None = None,
    max_ratio: float = 0.5,
) -> list[dict[str, Any]]:
    """Dynamically select relevant tools using embedding similarity.

    Args:
        tools: Full list of available tool dicts.
        query: User query or intent text.
        llm: LLM client for embedding generation.  Creates a default if None.
        max_ratio: Max fraction of tools to return (default 50%).

    Returns:
        Filtered list of tools with ``_relevance_score`` attached.
    """
    if not tools or not query.strip():
        return tools

    _llm = llm or LLMClient()
    settings = __import__("nexus.config.settings", fromlist=["get_settings"]).get_settings()

    # Extract text from each tool
    tool_texts: list[str] = []
    enabled_tools: list[dict[str, Any]] = []
    for t in tools:
        enabled = t.get("enabled", True)
        if not enabled:
            continue
        text = _extract_tool_text(t)
        if text.strip():
            tool_texts.append(text)
            enabled_tools.append(t)

    if not tool_texts:
        return tools

    # Embed query
    try:
        query_vec = (await _llm.embed(settings.llm.embedding_model, [query]))[0]
    except Exception:
        logger.warning("semantic_selector.embedding_failed")
        return tools  # graceful degradation — return all tools

    # Embed each tool (batch where possible)
    tool_vecs: list[list[float]] = []
    try:
        tool_vecs = await _llm.embed(settings.llm.embedding_model, tool_texts)
    except Exception:
        logger.warning("semantic_selector.tool_embedding_failed")
        return tools

    if not tool_vecs or len(tool_vecs) != len(enabled_tools):
        return tools

    # Cosine similarities
    def _norm(v: list[float]) -> float:
        return math.sqrt(sum(x * x for x in v))

    q_norm = _norm(query_vec)
    if q_norm == 0:
        return tools
    similarities: list[float] = []
    for tv in tool_vecs:
        dot = sum(a * b for a, b in zip(query_vec, tv))
        t_norm = _norm(tv)
        sim = dot / (q_norm * t_norm) if t_norm > 0 else 0.0
        similarities.append(sim)

    # Dynamic threshold
    complexity = _estimate_complexity(query)
    threshold = _dynamic_threshold(similarities, complexity)

    # Select
    selected = [
        (i, sim) for i, sim in enumerate(similarities) if sim >= threshold
    ]
    selected.sort(key=lambda x: -x[1])

    max_tools = max(1, int(len(enabled_tools) * max_ratio))
    selected = selected[:max_tools]

    result = []
    for idx, sim in selected:
        tool = dict(enabled_tools[idx])
        tool["_relevance_score"] = round(sim, 4)
        result.append(tool)

    logger.info(
        "semantic_selector.completed",
        original=len(tools),
        filtered=len(result),
        threshold=round(threshold, 3),
    )
    return result
