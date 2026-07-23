"""understand_intent node — parse user message into structured intent."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from typing import Any

import structlog

from nexus.agent.nodes import msg_content, msg_role
from nexus.agent.prompts import prompt_manager
from nexus.agent.state import AgentState, IntentAnalysis
from nexus.config.settings import get_settings
from nexus.llm.client import LLMClient
from nexus.utils.json_extractor import JsonExtractor

logger = structlog.get_logger("nexus.agent.nodes.understand_intent")

_json_extractor = JsonExtractor()


def _openai_message(role: str, content: str, **kwargs: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": role, "content": content}
    msg.update(kwargs)
    return msg


def _is_complex_query(query: str) -> bool:
    """Detect compound/multi-intent queries — purely heuristic, no tool names.

    Returns True for queries that likely contain multiple distinct requests
    requiring deeper reasoning (conjunctions, long text, multiple questions).
    """
    q = query.lower().strip()
    if not q:
        return False
    # Long queries or those with explicit conjunctions
    conjunctions = {" and ", " also ", " too ", " plus "}
    has_conj = any(c in q for c in conjunctions)
    # Multiple question marks or imperative verbs suggesting separate intents
    multi_intent = q.count("?") > 1 or q.count(".") > 1
    # Follow-up short queries are NOT complex
    is_followup = len(q) < 15 and not has_conj
    if is_followup:
        return False
    return len(q) > 60 or has_conj or multi_intent


def _compute_task_difficulty(analysis: IntentAnalysis, last_user: str) -> float:
    """Estimate task difficulty from 0 (easy) to 1 (hard).

    Factors:
    - Number of missing info slots (0 → 0, 3+ → 0.3)
    - Number of implied actions (0 → 0, 3+ → 0.2)
    - Query length (very short <10 chars → 0.2 ambiguous)
    - Confidence inversely (1 - confidence) * 0.3
    """
    difficulty = 0.0
    n_missing = len(analysis.missing_info_slots)
    difficulty += min(n_missing / 10.0, 0.3)
    n_actions = len(analysis.implied_actions)
    difficulty += min(n_actions / 10.0, 0.2)
    if len(last_user.strip()) < 10:
        difficulty += 0.2
    difficulty += (1.0 - analysis.confidence) * 0.3
    return min(difficulty, 1.0)


async def understand_intent(
    state: AgentState,
    llm: LLMClient,
    model: str,
    session_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Parse the latest user message into structured intent via prompt templates.

    Uses multi-level confidence bands for routing:
    - confidence >= 0.9: proceed directly
    - 0.7 <= confidence < 0.9: proceed with enhanced reflection
    - 0.5 <= confidence < 0.7: self-consistency sampling
    - confidence < 0.5: ask for clarification

    Also computes task_difficulty for adaptive reflection thresholding.

    Returns:
        Dict with ``intent``, ``missing_info_slots``, ``messages``,
        ``intent_analysis``, ``task_difficulty``, and ``_routing_decision``.
    """
    messages: list = list(state.get("messages", []))
    new_messages: list[dict[str, Any]] = []
    last_user = next(
        (msg_content(m) for m in reversed(messages) if msg_role(m) == "user"),
        "",
    )
    if not last_user:
        return {"intent": None, "missing_info_slots": [], "is_high_risk": False, "_routing_decision": "finalize"}

    # Build conversation context: original user query + last 8 messages
    all_msgs = list(messages)
    first_user = next(
        (msg_content(m) for m in all_msgs if msg_role(m) == "user"),
        "",
    )
    context_messages: list[dict[str, Any]] = []
    if first_user:
        context_messages.append({"role": "user", "content": first_user[:400]})
    for m in all_msgs[-4:]:
        role = msg_role(m)
        if role in ("user", "assistant", "system", "tool"):
            text = msg_content(m)[:300]
            if text and text != first_user[:300]:
                context_messages.append({"role": role, "content": text})

    gathered: dict[str, Any] = state.get("gathered_requirements", {})
    # Extract entities from previous user messages for cross-turn context
    prior_entities: dict[str, str] = {}
    for m in all_msgs[:-1]:  # exclude current message
        if msg_role(m) == "user":
            text = msg_content(m)
            # Extract "about X" or "tell me about X" patterns
            import re as _re
            for match in _re.finditer(r'(?:about|for|of|regarding)\s+["\']?(\w+(?:\s+\w+){0,3})["\']?', text, _re.I):
                val = match.group(1).strip()
                if val and len(val) > 1:
                    prior_entities[f"known_{len(prior_entities)}"] = val
    gathered_context = (
        f"\nAlready gathered information: {json.dumps(gathered)}\n"
        if gathered
        else "\nNo information has been gathered yet.\n"
    )
    if prior_entities:
        gathered_context += f"\nHistorical context (from previous turns): {json.dumps(prior_entities)}\n"

    # Build context for dynamic example selection
    intent_text = (state.get("intent") or {}).get("intent", last_user[:100])
    example_context = {
        "response_type": state.get("response_type", "tool"),
        "intent": intent_text,
    }

    # Dynamic prompt depth — no hardcoded tools, purely heuristic
    is_complex = _is_complex_query(last_user)
    version = "4.0-complex" if is_complex else "4.0-simple"
    n_examples = 2 if is_complex else 0
    n_mistakes = 2 if is_complex else 0

    system_prompt = prompt_manager.render_with_examples(
        "understand_intent",
        version=version,
        context=example_context,
        max_examples=n_examples,
        max_mistakes=n_mistakes,
    )
    system_prompt = system_prompt.replace(
        "<output_format>",
        f"{gathered_context}\n<output_format>",
    )

    # Inject available tools context for accurate needs_tool routing
    available_tools = state.get("available_tools", [])
    if available_tools:
        tool_names = ", ".join(t.get("name", "") for t in available_tools)
        system_prompt = (
            f"<available_tools>{tool_names}</available_tools>\n\n{system_prompt}"
        )

    # Inject relevant long-term memories via MemoryScout (proactive, multi-trigger)
    _memory_ctx: str = ""
    try:
        from nexus.memory.scout import MemoryScout  # noqa: PLC0415
        _scout = MemoryScout(llm=llm)
        # Skip scout for greetings to save cost (no memory needed)
        if state.get("response_type") not in ("greeting", "meta"):
            _memory_ctx = await _scout.scout(
                trigger="intent", context={"intent": intent_text, "query": last_user}
            ) or ""
    except Exception:
        pass
    if _memory_ctx:
        system_prompt = _memory_ctx + "\n\n" + system_prompt

    # Inject working memory context
    try:
        from nexus.memory.working import WorkingMemory  # noqa: PLC0415
        wm = WorkingMemory.from_dict(state.get("working_memory"))
        wm_ctx = wm.to_context(n=5)
        if wm_ctx:
            system_prompt = wm_ctx + "\n\n" + system_prompt
    except Exception:
        logger.warning("memory.wm_injection_failed", exc_info=True)

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
        max_tokens=1024 if is_complex else 512,
        response_format={"type": "json_object"},
    )

    content = _json_extractor.extract(response.content or "")

    # Strip markdown code fences if present
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

    # Fallback: if LLM returned empty/zero-confidence intent, use
    # embedding-based tool matching via ToolRegistry (no extra LLM call).
    # This handles cases where the model doesn't recognize entity names
    # (e.g. "Husnain", "PKR") but the tools can still handle them.
    if (not analysis.primary_goal or analysis.confidence == 0.0) and last_user.strip() and session_factory is not None:
        try:
            from nexus.tools.registry import ToolRegistry  # noqa: PLC0415
            reg = ToolRegistry(llm=llm)
            async with session_factory() as sess:
                results = await reg.search_semantic(sess, last_user, k=3)
            if results:
                matched = [(r.tool.name, r.score) for r in results if r.score >= 0.3]
                if matched:
                    analysis.primary_goal = ", ".join(t[0] for t in matched)
                    analysis.confidence = 0.6
                    logger.info("intent.fallback_embedding_success", tools=matched)
        except Exception as exc:
            logger.warning("intent.fallback_embedding_failed", error=str(exc))

    # Compute task difficulty for adaptive reflection
    task_difficulty = _compute_task_difficulty(analysis, last_user)

    # Populate gathered_requirements from known_parameters and resolved missing slots
    prev_missing: list[str] = state.get("missing_info_slots") or []
    new_missing_names: list[str] = [s.name for s in analysis.missing_info_slots]
    resolved = [name for name in prev_missing if name not in new_missing_names]
    gathered = dict(state.get("gathered_requirements", {}))
    if resolved and last_user:
        for name in resolved:
            gathered[name] = last_user
    known_vals: dict[str, str] = analysis.known_parameters
    for name, val in known_vals.items():
        gathered[name] = val

    missing_slot_names = new_missing_names
    merged_params: dict[str, Any] = dict(known_vals)
    for s in analysis.missing_info_slots:
        if s.name not in merged_params:
            merged_params[s.name] = None
    intent_dict: dict[str, Any] = {
        "intent": analysis.primary_goal,
        "parameters": merged_params,
    }

    # Determine if this is a high-risk intent (tool requires approval)
    is_high_risk = False
    try:
        available_tools = state.get("available_tools", [])
        intent_goal = analysis.primary_goal.lower() if analysis.primary_goal else ""
        for t in available_tools:
            tname = (t.get("name") or "").lower()
            tdesc = (t.get("description") or "").lower()
            tcat = (t.get("category") or "").lower()
            if tname and (tname in intent_goal or tname in tdesc):
                if t.get("requires_approval") or t.get("risk_level") in ("medium", "high"):
                    is_high_risk = True
                    break
    except Exception:
        pass

    # Add working memory entry for parsed intent
    try:
        from nexus.memory.working import WorkingMemory  # noqa: PLC0415
        wm = WorkingMemory.from_dict(state.get("working_memory"))
        wm.add(
            key="intent",
            content=analysis.primary_goal,
            source="inference",
            importance=analysis.confidence,
            turn_id=state.get("iteration_count", 0),
        )
        working_memory_update = wm.to_dict()
    except Exception:
        working_memory_update = state.get("working_memory", {"entries": []})

    response_type = analysis.response_type if hasattr(analysis, "response_type") else "tool"
    needs_tool = analysis.needs_tool if hasattr(analysis, "needs_tool") else True

    # Non-tool queries route to respond_without_tool regardless of confidence
    if not needs_tool:
        return {
            "messages": new_messages,
            "intent": intent_dict,
            "missing_info_slots": missing_slot_names,
            "intent_analysis": analysis.model_dump(mode="json"),
            "response_type": response_type,
            "iteration_count": state.get("iteration_count", 0) + 1,
            "gathered_requirements": gathered,
            "task_difficulty": task_difficulty,
            "working_memory": working_memory_update,
            "is_high_risk": is_high_risk,
            "_routing_decision": "respond_without_tool",
        }

    # ── Multi-level confidence routing ──
    adapt = get_settings().agent.adaptive_reflection
    confidence = analysis.confidence

    if confidence < adapt.confidence_low:
        # < 0.5: Ask for clarification
        meta_question = (
            f"I'm not entirely sure I understand. "
            f'You said: "{last_user[:100]}". '
            f"I think you want to {analysis.primary_goal}, "
            f"but I'm not confident (score: {confidence:.2f}). "
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
            "task_difficulty": task_difficulty,
            "confidence": confidence,
            "is_high_risk": is_high_risk,
            "working_memory": working_memory_update,
            "_routing_decision": "ask",
        }

    if confidence < adapt.confidence_moderate:
        # 0.5–0.7: Lightweight verify (single critique call)
        return {
            "messages": new_messages,
            "intent": intent_dict,
            "missing_info_slots": missing_slot_names,
            "intent_analysis": analysis.model_dump(mode="json"),
            "response_type": "tool",
            "iteration_count": state.get("iteration_count", 0) + 1,
            "gathered_requirements": gathered,
            "task_difficulty": task_difficulty,
            "confidence": confidence,
            "working_memory": working_memory_update,
            "is_high_risk": is_high_risk,
            "_routing_decision": "lightweight_verify",
        }

    # confidence >= confidence_moderate (0.7): proceed normally
    return {
        "messages": new_messages,
        "intent": intent_dict,
        "missing_info_slots": missing_slot_names,
        "intent_analysis": analysis.model_dump(mode="json"),
        "response_type": "tool",
        "iteration_count": state.get("iteration_count", 0) + 1,
        "gathered_requirements": gathered,
        "task_difficulty": task_difficulty,
        "confidence": confidence,
        "is_high_risk": is_high_risk,
        "working_memory": working_memory_update,
    }
