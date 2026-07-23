"""respond_without_tool node — answer queries that don't need tool invocation.

Handles three categories dynamically based on ``response_type`` from intent
analysis: greeting, meta (about-agent), and memory_query (about past
interactions).  No tool discovery, planning, or execution occurs.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from nexus.agent.nodes import msg_content
from nexus.agent.state import RESPONSE_TYPES
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.agent.nodes.respond_without_tool")


def _openai_message(role: str, content: str, **kwargs: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": role, "content": content}
    msg.update(kwargs)
    return msg


async def respond_without_tool(
    state: dict[str, Any],
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Generate a direct response for queries that don't need tools.

    Reads ``response_type`` from agent state and delegates to the
    appropriate handler.  Each handler builds its prompt dynamically
    from available context (tools list, memory, conversation history).

    Returns:
        Dict with ``final_response``, ``messages``, and ``_routing_decision``.
    """
    response_type: str = state.get("response_type", "greeting")
    messages: list = list(state.get("messages", []))
    last_user = next(
        (msg_content(m) for m in reversed(messages) if msg_content(m)),
        "",
    )
    query = last_user or ""

    if response_type == "meta":
        final = await _handle_meta(state, llm, model, query)
    elif response_type == "memory_query":
        final = await _handle_memory_query(state, llm, model, query)
    else:
        final = await _handle_greeting(state, llm, model, query)

    final_msg = _openai_message("assistant", final, _milestone=True)
    logger.info("respond_without_tool.completed", response_type=response_type, length=len(final))
    return {
        "final_response": final,
        "messages": [final_msg],
        "_routing_decision": "finalize",
    }


def _build_tool_list(tools: list[dict[str, Any]]) -> str:
    """Build a dynamic tool listing from available tools in state."""
    if not tools:
        return "I don't have any specific tools configured yet."
    lines: list[str] = []
    for t in tools:
        name = t.get("name", "unknown")
        desc = t.get("description", "")
        lines.append(f"- **{name}**: {desc}" if desc else f"- **{name}**")
    return "\n".join(lines)


_GREETINGS = [
    "Hello! How can I help you today?",
    "Hi there! How can I assist you?",
    "Hello! I'm here to help. What can I do for you?",
    "Hey! How can I help you today?",
]


async def _handle_greeting(
    state: dict[str, Any],
    llm: LLMClient,
    model: str,
    query: str,
) -> str:
    """Friendly greeting response — no tools, no memory needed (static template)."""
    import random
    return random.choice(_GREETINGS)


def _format_tool_list(tools: list[dict[str, Any]]) -> str:
    """Build a human-readable tool listing grouped by category."""
    if not tools:
        return ""
    by_cat: dict[str, list[str]] = {}
    for t in tools:
        cat = t.get("category") or "other"
        name = t.get("name", "unknown")
        desc = t.get("description", "")
        line = f"  - **{name}**: {desc}" if desc else f"  - **{name}**"
        by_cat.setdefault(cat, []).append(line)

    parts: list[str] = []
    for cat in sorted(by_cat):
        parts.append(f"**{cat.capitalize()}**:")
        parts.extend(by_cat[cat])
    return "\n".join(parts)


async def _handle_meta(
    state: dict[str, Any],
    llm: LLMClient,
    model: str,
    query: str,
) -> str:
    """Describe agent capabilities using the dynamically discovered tools list.

    Uses template-based tool listing (no LLM) for speed and accuracy.
    Falls back to _meta_fallback only if no tools are registered.
    """
    tools = state.get("available_tools", [])
    tool_count = len(tools)
    categories = set()
    for t in tools:
        cat = t.get("category") or t.get("tags", [None])[0] if t.get("tags") else None
        if cat:
            categories.add(cat)
    cats_str = ", ".join(sorted(categories)) if categories else "various"

    if not tools:
        return _meta_fallback(tool_count, cats_str)

    try:
        tool_lines = _format_tool_list(tools)
        return (
            f"I'm Nexus Agent, and I have {tool_count} tools available "
            f"across {cats_str} categories:\n\n{tool_lines}\n\n"
            "What would you like help with?"
        )
    except Exception:
        return _meta_fallback(tool_count, cats_str)


def _meta_fallback(tool_count: int, categories: str) -> str:
    """Fallback when LLM call fails — no API needed."""
    if tool_count == 0:
        return "I'm Nexus Agent, your conversational AI assistant. I can chat, answer questions, and help with various tasks."
    return (
        f"I'm Nexus Agent, and I have {tool_count} tools available across "
        f"{categories} categories. I can search the web, manage bookmarks, "
        f"look up information, and more. What would you like help with?"
    )


async def _handle_memory_query(
    state: dict[str, Any],
    llm: LLMClient,
    model: str,
    query: str,
) -> str:
    """Answer questions about past conversations by retrieving memories."""
    memories_text = ""
    try:
        from nexus.memory.manager import MemoryManager  # noqa: PLC0415
        from nexus.memory.store import MemoryStore  # noqa: PLC0415

        mgr = MemoryManager(store=MemoryStore(), llm=llm)
        memories_text = await mgr.retrieve_formatted(query=query)
    except Exception as exc:
        logger.warning("respond_without_tool.memory_retrieval_failed", error=str(exc))

    context = memories_text if memories_text else "No relevant past memories found."
    prompt = (
        "<role>You are Nexus Agent, an AI assistant with memory of past conversations.</role>\n"
        "<context>The user is asking about past interactions or information "
        "you might remember from previous conversations.</context>\n"
        "<instructions>\n"
        "1. Use the retrieved memories below to answer the user's question.\n"
        "2. If no relevant memories exist, politely explain that you don't "
        "recall previous interactions on this topic.\n"
        "3. Be concise — 2-3 sentences.\n"
        "4. Do NOT fabricate memories. Only use what's provided.\n"
        "</instructions>\n"
        f"<memories>\n{context}\n</memories>\n"
    )
    response = await llm.complete(
        model=model,
        messages=[_openai_message("user", prompt + f"\nUser question: {query}")],
        temperature=0.7,
        max_tokens=200,
        stop=["User:", "user:", "###"],
    )
    return response.content or "I don't have any relevant memories to share."
