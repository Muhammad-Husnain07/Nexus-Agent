"""understand_intent node — parse user message into structured intent."""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from nexus.agent.nodes import msg_content, msg_role
from nexus.agent.prompts import prompt_manager
from nexus.agent.state import AgentState, IntentAnalysis
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.agent.nodes.understand_intent")


def _openai_message(role: str, content: str, **kwargs: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": role, "content": content}
    msg.update(kwargs)
    return msg


async def understand_intent(
    state: AgentState,
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Parse the latest user message into structured intent via prompt templates.

    Merges ``gathered_requirements`` from prior turns into the context so
    the LLM can re-evaluate what is still missing.  If confidence < 0.5
    the node routes to clarification with a meta-question.

    Returns:
        Dict with ``intent``, ``missing_info_slots``, ``messages``,
        ``intent_analysis``, and ``_routing_decision`` updates.
    """
    messages: list = list(state.get("messages", []))
    new_messages: list[dict[str, Any]] = []
    last_user = next(
        (msg_content(m) for m in reversed(messages) if msg_role(m) == "user"),
        "",
    )
    if not last_user:
        return {"intent": None, "missing_info_slots": [], "_routing_decision": "finalize"}

    # Build conversation context: original user query + last 8 messages
    all_msgs = list(messages)
    first_user = next(
        (msg_content(m) for m in all_msgs if msg_role(m) == "user"),
        "",
    )
    context_messages: list[dict[str, Any]] = []
    if first_user:
        context_messages.append({"role": "user", "content": first_user[:800]})
    for m in all_msgs[-8:]:
        role = msg_role(m)
        if role in ("user", "assistant", "system", "tool"):
            text = msg_content(m)[:500]
            if text and text != first_user[:500]:
                context_messages.append({"role": role, "content": text})

    gathered: dict[str, Any] = state.get("gathered_requirements", {})
    gathered_context = (
        f"\nAlready gathered information: {json.dumps(gathered)}\n"
        if gathered
        else "\nNo information has been gathered yet.\n"
    )

    _tmpl = prompt_manager.get("understand_intent", version="3.0")
    system_prompt = prompt_manager.render(
        "understand_intent",
        version="3.0",
        examples=_tmpl.metadata.get("few_shot", ""),
    )
    system_prompt = system_prompt.replace(
        "<output_format>",
        f"{gathered_context}\n<output_format>",
    )

    # Inject relevant long-term memories into the system prompt
    try:
        from nexus.memory.manager import MemoryManager  # noqa: PLC0415
        from nexus.memory.store import MemoryStore  # noqa: PLC0415
        _memory_mgr = MemoryManager(store=MemoryStore(), llm=llm)
        _memory_ctx = await _memory_mgr.retrieve_formatted(query=last_user)
        if _memory_ctx:
            system_prompt = _memory_ctx + "\n\n" + system_prompt
    except Exception:
        logger.warning("memory.injection_failed", exc_info=True)

    # Inject reflection feedback when re-entering from a reflection revise
    reflection_feedback = state.get("reflection_feedback", "") or ""
    if reflection_feedback:
        system_prompt = (
            f"<previous_response_feedback>\n{reflection_feedback}\n"
            f"</previous_response_feedback>\n\n{system_prompt}"
        )

    response = await llm.complete(
        model=model,
        messages=[
            _openai_message("system", system_prompt),
            *context_messages,
            _openai_message("user", last_user),
        ],
        temperature=0,
    )

    content = (response.content or "").strip()
    # Try to extract JSON from a larger response (handle LLM preamble)
    json_match = re.search(r"\{[\s\S]*\}", content)
    if json_match:
        content = json_match.group(0).strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
        content = re.sub(r"\n```$", "", content)
        content = content.strip()
    try:
        parsed: dict[str, Any] = json.loads(content or "{}")
        analysis = IntentAnalysis(**parsed)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("intent.parse_failed", content=response.content, error=str(exc))
        analysis = IntentAnalysis(
            primary_goal="",
            implied_actions=[],
            missing_info_slots=[],
            confidence=0.0,
            urgency="normal",
        )
    except Exception as exc:
        logger.warning("intent.validation_failed", error=str(exc))
        analysis = IntentAnalysis(
            primary_goal="",
            implied_actions=[],
            missing_info_slots=[],
            confidence=0.0,
            urgency="normal",
        )

    # Populate gathered_requirements from known_parameters and resolved missing slots
    prev_missing: list[str] = state.get("missing_info_slots") or []
    new_missing_names: list[str] = [s.name for s in analysis.missing_info_slots]
    resolved = [name for name in prev_missing if name not in new_missing_names]
    gathered = dict(state.get("gathered_requirements", {}))
    if resolved and last_user:
        for name in resolved:
            gathered[name] = last_user
    # Add any known_parameters extracted by the LLM
    known_vals: dict[str, str] = analysis.known_parameters
    for name, val in known_vals.items():
        gathered[name] = val

    missing_slot_names = new_missing_names
    # Build parameters: known values merged with null placeholders for truly missing ones
    merged_params: dict[str, Any] = dict(known_vals)
    for s in analysis.missing_info_slots:
        if s.name not in merged_params:
            merged_params[s.name] = None
    intent_dict: dict[str, Any] = {
        "intent": analysis.primary_goal,
        "parameters": merged_params,
    }

    new_messages.append(_openai_message("assistant", f"Parsed intent: {analysis.primary_goal}"))

    # Determine response type from the analysis
    response_type = analysis.response_type if hasattr(analysis, "response_type") else "tool"
    needs_tool = analysis.needs_tool if hasattr(analysis, "needs_tool") else True

    # Non-tool queries (greeting, meta, memory) route to respond_without_tool
    # regardless of confidence — these don't need tool discovery
    if not needs_tool:
        return {
            "messages": new_messages,
            "intent": intent_dict,
            "missing_info_slots": missing_slot_names,
            "intent_analysis": analysis.model_dump(mode="json"),
            "response_type": response_type,
            "iteration_count": state.get("iteration_count", 0) + 1,
            "gathered_requirements": gathered,
        }

    if analysis.confidence < 0.5:
        meta_question = (
            f"I'm not entirely sure I understand. "
            f'You said: "{last_user[:100]}". '
            f"I think you want to {analysis.primary_goal}, "
            f"but I'm not confident (score: {analysis.confidence:.2f}). "
            f"Could you rephrase or clarify?"
        )
        new_messages.append(_openai_message("assistant", meta_question))
        return {
            "messages": new_messages,
            "intent": intent_dict,
            "missing_info_slots": missing_slot_names,
            "intent_analysis": analysis.model_dump(mode="json"),
            "final_response": meta_question,
            "response_type": "tool",
            "iteration_count": state.get("iteration_count", 0) + 1,
            "gathered_requirements": gathered,
            "_routing_decision": "ask",
        }

    return {
        "messages": new_messages,
        "intent": intent_dict,
        "missing_info_slots": missing_slot_names,
        "intent_analysis": analysis.model_dump(mode="json"),
        "response_type": "tool",
        "iteration_count": state.get("iteration_count", 0) + 1,
        "gathered_requirements": gathered,
    }
