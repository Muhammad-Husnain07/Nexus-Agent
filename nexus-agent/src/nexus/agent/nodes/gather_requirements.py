"""gather_requirements node — ask clarifying questions when info is missing."""

from __future__ import annotations

import json
from typing import Any

import structlog

from nexus.agent.prompts import prompt_manager
from nexus.agent.state import AgentState
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.agent.nodes.gather_requirements")

_MAX_QUESTIONS_PER_TURN = 3


def _openai_message(role: str, content: str, **kwargs: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": role, "content": content}
    msg.update(kwargs)
    return msg


async def gather_requirements(
    state: AgentState,
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Ask clarifying questions when required information is missing.

    Generates at most ``_MAX_QUESTIONS_PER_TURN`` questions.  Reads from
    ``gathered_requirements`` to know what's already known and only asks
    about what's still missing.  Tracks the interaction so the next turn
    of ``understand_intent`` can merge the new info.

    Returns:
        Dict with updated ``messages``, ``final_response``, updated
        ``gathered_requirements``, and resets ``missing_info_slots``.
    """
    missing: list[str] = state.get("missing_info_slots") or []
    
    # Check for reflection issue context (from reflect_on_response approach_issue)
    gathered = state.get("gathered_requirements", {}) or {}
    reflection_issue = gathered.pop("_reflection_issue", None) if isinstance(gathered, dict) else None

    if not missing and not reflection_issue:
        return {"final_response": None, "missing_info_slots": []}

    # Build detail for each slot from intent_analysis if available
    intent_analysis_raw: dict[str, Any] | None = state.get("intent_analysis")
    slots_detail: str = ""
    if intent_analysis_raw:
        slots_list = intent_analysis_raw.get("missing_info_slots", [])
        for slot in slots_list:
            if slot["name"] in missing:
                detail = f"- {slot['name']}: {slot.get('description', '')}"
                if slot.get("why_needed"):
                    detail += f" (needed: {slot['why_needed']})"
                if slot.get("possible_values"):
                    detail += f" [options: {', '.join(slot['possible_values'])}]"
                slots_detail += detail + "\n"

    questions_asked: int = state.get("questions_asked", 0)
    max_q = max(1, _MAX_QUESTIONS_PER_TURN - questions_asked)

    system_prompt = prompt_manager.render(
        "gather_requirements",
        missing_summary="\n".join(f"- {slot}" for slot in missing) if missing else (reflection_issue or "No data found"),
        max_questions=str(max_q),
        slots_detail=slots_detail or reflection_issue or "No additional details available.",
        reflection_context=reflection_issue or "",
    )

    response = await llm.complete(
        model=model,
        messages=[
            _openai_message("system", system_prompt),
            _openai_message(
                "user",
                f"Please ask me about: {', '.join(missing) if missing else reflection_issue or 'the required information'}\n"
                f"Already known: {json.dumps(gathered) if gathered else 'nothing yet'}",
            ),
        ],
        temperature=0.7,
    )
    question: str = response.content or "Could you please provide more details?"

    question_msg = _openai_message("assistant", question)

    return {
        "messages": [question_msg],
        "final_response": question,
        "missing_info_slots": missing,  # keep until user answers
        "questions_asked": questions_asked + 1,
        "_routing_decision": "ask",
    }
