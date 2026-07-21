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

    final_msg = _openai_message("assistant", final)
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


async def _handle_greeting(
    state: dict[str, Any],
    llm: LLMClient,
    model: str,
    query: str,
) -> str:
    """Friendly greeting response — no tools, no memory needed."""
    prompt = (
        "<role>You are Nexus Agent, a helpful AI assistant.</role>\n"
        "<context>The user is greeting you or making casual conversation. "
        "Respond warmly and briefly, then offer assistance.</context>\n"
        "<instructions>\n"
        "1. Acknowledge the user's greeting or message naturally.\n"
        "2. Keep your response to 1-2 sentences.\n"
        "3. End with a brief offer of help (e.g., 'How can I assist you today?').\n"
        "</instructions>\n"
    )
    response = await llm.complete(
        model=model,
        messages=[_openai_message("user", prompt + f"\nUser message: {query}")],
        temperature=0.7,
    )
    return response.content or "Hello! How can I help you today?"


async def _handle_meta(
    state: dict[str, Any],
    llm: LLMClient,
    model: str,
    query: str,
) -> str:
    """Describe agent capabilities using the dynamically discovered tools list."""
    tools = state.get("available_tools", [])
    tool_listing = _build_tool_list(tools)

    prompt = (
        "<role>You are Nexus Agent, an AI assistant that helps users by calling "
        "external tools and APIs.</role>\n"
        "<context>The user is asking about what you can do. Describe your "
        "capabilities based on the tools you have access to.</context>\n"
        "<instructions>\n"
        "1. Greet the user and explain your role briefly.\n"
        "2. List the capabilities you have based on the available tools below.\n"
        "3. Keep your response conversational and concise (3-5 sentences).\n"
        "4. If no tools are configured, explain that you're a conversational assistant.\n"
        "</instructions>\n"
        f"<available_tools>\n{tool_listing}\n</available_tools>\n"
    )
    response = await llm.complete(
        model=model,
        messages=[_openai_message("user", prompt + f"\nUser question: {query}")],
        temperature=0.7,
    )
    return response.content or "I'm Nexus Agent, your AI assistant. I can help you with various tasks."


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
    )
    return response.content or "I don't have any relevant memories to share."
