"""RequirementCollectorNode — interactive requirement gathering loop.

Replaces the old dead-end ClarificationNode with an iterative loop that
asks clarifying questions until enough information is gathered, then
routes to the SemanticPlannerNode for compilation.

The graph terminates after each question turn. On the user's reply,
the graph resumes and Re-enters this node to evaluate whether the
new information satisfies all requirements.
"""

from __future__ import annotations

import time as _time
import uuid
from typing import Any

import structlog

from nexus.agent.intent import Intent
from nexus.agent.state import AgentState
from nexus.config.settings import get_settings

logger = structlog.get_logger("nexus.agent.nodes.requirement_collector")


async def requirement_collector_node(
    state: AgentState,
    llm: Any = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Gather missing requirements iteratively.

    Reads ``_clarification_slots`` from state (accumulated key-value pairs).
    If confidence >= ``min_confidence_to_skip``, routes to planner.
    If not enough info, emits a question and ends the graph turn.

    On re-entry (user replied to a prior question), the new info is
    detected via ``_clarification_history`` and merged into slots.
    Refusal detection is LLM-driven (no hardcoded word lists).
    """
    settings = get_settings().agent.requirement_collector

    # Load current collection state
    slots: dict[str, Any] = state.get("_clarification_slots", {})
    rounds: int = state.get("_clarification_rounds", 0)
    intent: dict[str, Any] | None = state.get("intent")

    # Check if we can skip the collector entirely
    if intent is not None:
        intent_obj = Intent(**intent) if isinstance(intent, dict) else intent
        if intent_obj.confidence >= settings.min_confidence_to_skip:
            logger.info(
                "requirement_collector.skipped",
                confidence=intent_obj.confidence,
                threshold=settings.min_confidence_to_skip,
            )
            return {
                "_ready_to_plan": True,
                "_route_to_planner": True,
            }

    # Build missing slots from intent or from what we already collected
    missing_slots: list[dict[str, Any]] = []
    if intent is not None:
        intent_obj = Intent(**intent) if isinstance(intent, dict) else intent
        for spec in intent_obj.missing_info:
            if spec.name not in slots:
                missing_slots.append({
                    "name": spec.name,
                    "question": spec.question,
                    "options": spec.options,
                    "required": spec.required,
                })

    # Consume the latest user message exactly once (by message id), filling
    # the slot that was asked for. This prevents the same message from
    # generating junk slots on every graph re-entry (infinite loop fix).
    consumed: list[str] = list(state.get("_clarification_consumed_msgs", []))
    new_info, consumed_id = await _consume_new_info(state, missing_slots, consumed, llm, model)

    if new_info is not None:
        slots = {**slots, **new_info}
        rounds += 1
        if consumed_id:
            consumed = consumed + [consumed_id]
        logger.info(
            "requirement_collector.slot_filled",
            new_slots=list(new_info.keys()),
            total_slots=len(slots),
            round=rounds,
        )
        # Re-evaluate after merge
        missing_slots = _re_evaluate_missing(state, slots)
        if not missing_slots and (
            intent is None
            or Intent(**intent).confidence >= settings.min_confidence_to_proceed
        ):
            logger.info("requirement_collector.complete", slots=len(slots), rounds=rounds)
            return {
                "_clarification_slots": slots,
                "_clarification_rounds": rounds,
                "_clarification_consumed_msgs": consumed,
                "_ready_to_plan": True,
                "_clarification_history": state.get("_clarification_history", []) + ["resolved"],
            }

    # Enforce max rounds
    if rounds >= settings.max_rounds:
        logger.info("requirement_collector.max_rounds", rounds=rounds)
        return {
            "_clarification_slots": slots,
            "_clarification_rounds": rounds,
            "_clarification_consumed_msgs": consumed,
            "_ready_to_plan": True,
            "_route_to_planner": True,
        }

    # Pick the first missing slot to ask about
    if missing_slots:
        target = missing_slots[0]
        question = target["question"]
        asked_spec = target["name"]
    else:
        question = _build_generic_question(state, slots)
        asked_spec = None

    logger.info(
        "requirement_collector.asked",
        question=question,
        spec=asked_spec,
        round=rounds,
        filled=len(slots),
        missing=len(missing_slots),
    )

    # Record what was asked so the next turn can detect resolution
    asked_entry = {
        "question": question,
        "spec": asked_spec,
        "asked_at": _now_ts(),
    }
    history: list[dict[str, Any]] = list(state.get("_clarification_history", []))
    history.append(asked_entry)

    return {
        "final_response": question,
        "_routing_decision": "finalize",
        "response_type": "clarification",
        "_clarification_asked": asked_entry,
        "_clarification_slots": slots,
        "_clarification_rounds": rounds,
        "_clarification_consumed_msgs": consumed,
        "_clarification_history": history,
        "messages": [
            {
                "role": "assistant",
                "content": question,
                "id": str(uuid.uuid4()),
            }
        ],
    }


async def _consume_new_info(
    state: AgentState,
    missing_slots: list[dict[str, Any]],
    consumed: list[str],
    llm: Any = None,
    model: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Extract new info from the latest user message, if not already consumed.

    Returns ``(new_info, consumed_id)``. ``new_info`` is None when the
    latest message was already consumed, is a refusal (LLM-classified), or
    does not answer the most recently asked slot question.
    """
    last_user = _last_user_message(state)
    if last_user is None:
        return None, None
    msg_id = str(last_user.get("id") or "")
    if not msg_id or msg_id in consumed:
        return None, None
    new_info = await _detect_new_info(state, missing_slots, consumed, llm, model)
    if new_info is None:
        return None, None
    return new_info, msg_id


def _last_user_message(state: AgentState) -> dict[str, Any] | None:
    """Return the most recent user message dict (or None)."""
    messages: list = list(state.get("messages", []))
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            return m
    return None


async def _detect_new_info(
    state: AgentState,
    missing_slots: list[dict[str, Any]],
    consumed: list[str],
    llm: Any = None,
    model: str | None = None,
) -> dict[str, Any] | None:
    """Detect whether the user's latest turn answered a prior question.

    Only the latest user message is eligible, and only once (tracked via
    ``_clarification_consumed_msgs``). The reply fills the slot whose
    question was most recently asked (from ``_clarification_history``).
    Returns None if no new actionable info found.

    Refusal detection is LLM-driven — the model decides whether the reply
    is a refusal (skip/no/never mind/cancel) rather than an answer, so no
    word lists are hardcoded anywhere.
    """
    history: list = list(state.get("_clarification_history", []))
    if not history:
        return None

    last_user = _last_user_message(state)
    if last_user is None:
        return None
    msg_id = str(last_user.get("id") or "")
    content = str(last_user.get("content", ""))
    stripped = content.strip().lower()
    if msg_id in consumed or len(stripped) < 3:  # noqa: PLR2004
        return None

    # LLM-driven refusal detection — no hardcoded refusal words.
    if llm is not None and model is not None and await _is_refusal(llm, model, content):
        logger.info("requirement_collector.refusal_detected", message=content[:60])
        return None

    # The reply fills the slot whose question was asked last. Only a
    # specific slot question can be answered — a generic question does
    # not map to any slot, so it yields no new info (no junk keys).
    last_entry = history[-1] if history else None
    asked_spec = ""
    if isinstance(last_entry, dict):
        asked_spec = str(last_entry.get("spec") or "")
    if not asked_spec:
        return None

    still_missing = any(s["name"] == asked_spec for s in missing_slots)
    if not still_missing:
        return None
    return {asked_spec: content}


async def _is_refusal(llm: Any, model: str, content: str) -> bool:
    """LLM-driven refusal detection for the latest user reply.

    Returns True when the model classifies the reply as a refusal
    (skip/no/cancel/never mind/pass/i don't know/change of topic).
    On any failure the reply is treated as an answer (never blocks).
    """
    import json as _json

    system_prompt = (
        "You are classifying whether a user's reply to a clarifying question "
        "is a REFUSAL (skip, no, cancel, never mind, pass, i don't know, "
        "change of topic) or an actual ANSWER (provides the requested info). "
        "Return JSON with a single boolean key \"is_refusal\"."
    )
    try:
        response = await llm.complete(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content[:300]},
            ],
            temperature=0,
            max_tokens=16,
            response_format={"type": "json_object"},
        )
        if response.failed:
            return False
        data = _json.loads(response.content or "{}")
        return bool(data.get("is_refusal", False))
    except Exception:
        return False


def _re_evaluate_missing(
    state: AgentState,
    slots: dict[str, Any],
) -> list[dict[str, Any]]:
    """Re-evaluate what's still missing after a slot was filled.

    Reads fresh intent from state and removes now-satisfied slots.
    """
    intent_raw = state.get("intent")
    if intent_raw is None:
        return []
    intent = Intent(**intent_raw) if isinstance(intent_raw, dict) else intent_raw
    still_missing = []
    for spec in intent.missing_info:
        if spec.name not in slots:
            still_missing.append({
                "name": spec.name,
                "question": spec.question,
                "options": spec.options,
                "required": spec.required,
            })
    return still_missing


def _build_generic_question(
    state: AgentState,
    slots: dict[str, Any],
) -> str:
    """Build a fallback question when no specific slot is targeted.

    References the user's own latest message — never internal tool names.
    """
    last_user = _last_user_message(state)
    if last_user is not None:
        excerpt = str(last_user.get("content", "")).strip()[:120]
        if excerpt:
            return (
                f"I want to make sure I understand: can you tell me a bit "
                f"more about what you need regarding \"{excerpt}\"?"
            )
    return "Could you provide more details so I can help?"


def _now_ts() -> float:
    return _time.time()
