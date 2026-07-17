"""understand_intent node — parse user message into structured intent."""

from __future__ import annotations

import json
from typing import Any

import structlog

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
    messages: list[dict[str, Any]] = list(state.get("messages", []))
    last_user = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"),
        "",
    )
    if not last_user:
        return {"intent": None, "missing_info_slots": [], "_routing_decision": "finalize"}

    gathered: dict[str, Any] = state.get("gathered_requirements", {})
    gathered_context = (
        f"\nAlready gathered information: {json.dumps(gathered)}\n"
        if gathered
        else "\nNo information has been gathered yet.\n"
    )

    _tmpl = prompt_manager.get("understand_intent", version="2.0")
    system_prompt = prompt_manager.render(
        "understand_intent",
        version="2.0",
        examples=_tmpl.metadata.get("few_shot", ""),
    )
    system_prompt = system_prompt.replace(
        "**Output format (JSON):**",
        f"{gathered_context}\n**Output format (JSON):**",
    )

    response = await llm.complete(
        model=model,
        messages=[
            _openai_message("system", system_prompt),
            _openai_message("user", last_user),
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    try:
        parsed: dict[str, Any] = json.loads(response.content or "{}")
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

    messages.append(_openai_message("assistant", f"Parsed intent: {analysis.primary_goal}"))

    # Low-confidence routing
    if analysis.confidence < 0.5:
        meta_question = (
            f"I'm not entirely sure I understand. "
            f'You said: "{last_user[:100]}". '
            f"I think you want to {analysis.primary_goal}, "
            f"but I'm not confident (score: {analysis.confidence:.2f}). "
            f"Could you rephrase or clarify?"
        )
        messages.append(_openai_message("assistant", meta_question))
        return {
            "messages": messages,
            "intent": intent_dict,
            "missing_info_slots": missing_slot_names,
            "intent_analysis": analysis.model_dump(mode="json"),
            "final_response": meta_question,
            "iteration_count": state.get("iteration_count", 0) + 1,
            "gathered_requirements": gathered,
            "_routing_decision": "ask",
        }

    return {
        "messages": messages,
        "intent": intent_dict,
        "missing_info_slots": missing_slot_names,
        "intent_analysis": analysis.model_dump(mode="json"),
        "iteration_count": state.get("iteration_count", 0) + 1,
        "gathered_requirements": gathered,
    }
