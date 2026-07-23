"""self_consistency node — multi-sample aggregation for uncertainty.

For moderate-confidence queries (0.5–0.7), generates k parallel response
samples, checks agreement, and routes accordingly:

- High agreement (>80%): proceed with the most confident sample
- Low agreement (≤80%): ask user for clarification
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

from nexus.agent.prompts import prompt_manager
from nexus.agent.state import AgentState, IntentAnalysis
from nexus.config.settings import get_settings
from nexus.llm.client import LLMClient
from nexus.observability.tracing import get_tracer

logger = structlog.get_logger("nexus.agent.nodes.self_consistency")


def _openai_message(role: str, content: str, **kwargs: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": role, "content": content}
    msg.update(kwargs)
    return msg


def _parse_intent(content: str) -> dict[str, Any] | None:
    """Parse an LLM response into an IntentAnalysis dict."""
    if not content:
        return None
    content = content.strip()
    if content.startswith("```"):
        import re  # noqa: PLC0415
        content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
        content = re.sub(r"\n```$", "", content)
        content = content.strip()
    import re  # noqa: PLC0415
    # Strip CoT thinking tags
    content = re.sub(r"<thinking>[\s\S]*?</thinking>", "", content).strip()
    # Extract JSON
    json_match = re.search(r"\{[\s\S]*\}", content)
    if not json_match:
        return None
    try:
        parsed = json.loads(json_match.group(0))
        analysis = IntentAnalysis(**parsed)
        return analysis.model_dump(mode="json")
    except Exception:
        return None


def _compute_agreement(samples: list[dict[str, Any]]) -> float:
    """Compute agreement score among intent analysis samples.

    Compares primary_goal and needs_tool across samples.
    Returns 1.0 if all agree, 0.0 if none agree.
    """
    if len(samples) < 2:
        return 1.0

    goals = [s.get("primary_goal", "") for s in samples if s]
    tools = [s.get("needs_tool") for s in samples if s]

    if not goals:
        return 0.0

    # Goal agreement: check pairwise overlap
    goal_agreements = 0
    total_pairs = 0
    for i in range(len(goals)):
        for j in range(i + 1, len(goals)):
            total_pairs += 1
            g1 = goals[i].lower().strip()
            g2 = goals[j].lower().strip()
            if g1 == g2 or g1 in g2 or g2 in g1:
                goal_agreements += 1

    # Tool agreement: check all match
    tool_agree = all(t == tools[0] for t in tools) if tools else True

    goal_score = goal_agreements / total_pairs if total_pairs > 0 else 1.0
    tool_score = 1.0 if tool_agree else 0.0

    return (goal_score * 0.7) + (tool_score * 0.3)


def _pick_best_sample(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the sample with highest confidence."""
    best = samples[0]
    best_conf = best.get("confidence", 0.0) if best else 0.0
    for s in samples[1:]:
        conf = s.get("confidence", 0.0) if s else 0.0
        if conf > best_conf:
            best = s
            best_conf = conf
    return best or samples[0]


async def self_consistency(
    state: AgentState,
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Generate multiple samples for uncertain intents and pick the most consistent.

    Samples are generated in parallel (up to k). If agreement is high,
    the best sample is used and routing proceeds. If low, user is asked
    for clarification.

    Returns:
        Dict with ``intent_analysis`` (or ``final_response`` for clarify),
        ``_routing_decision``, and ``self_consistency_samples``.
    """
    adapt = get_settings().agent.adaptive_reflection
    k = adapt.self_consistency_k
    early_stop = adapt.self_consistency_early_stop

    last_user = ""
    messages: list = list(state.get("messages", []))
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            last_user = str(m.get("content", ""))
            break

    if not last_user:
        logger.warning("self_consistency.no_user_message")
        return {"_routing_decision": "ask", "final_response": "I'm not sure what you need. Could you rephrase?"}

    # Build a minimal system prompt for generating intent analysis
    system_prompt = prompt_manager.render("understand_intent", version="3.0")

    # Generate k samples in parallel
    async def _sample() -> dict[str, Any] | None:
        try:
            resp = await llm.complete(
                model=model,
                messages=[
                    _openai_message("system", system_prompt),
                    _openai_message("user", last_user),
                ],
                temperature=0.3,  # slight randomness for diversity
            )
            return _parse_intent(resp.content or "")
        except Exception:
            return None

    tasks = [_sample() for _ in range(k)]
    samples: list[dict[str, Any] | None] = await asyncio.gather(*tasks)

    # If early stop and first 2 agree, we can skip the rest (but they're already done)
    valid_samples = [s for s in samples if s is not None]

    if not valid_samples:
        logger.warning("self_consistency.all_samples_failed")
        return {
            "_routing_decision": "ask",
            "final_response": "I'm having trouble understanding your request. Could you rephrase it?",
        }

    agreement = _compute_agreement(valid_samples)

    # Store samples for potential downstream analysis
    sample_data = [
        {
            "primary_goal": s.get("primary_goal", ""),
            "confidence": s.get("confidence", 0.0),
        }
        for s in valid_samples
    ]

    _span_sc = get_tracer().start_span("agent.self_consistency")
    _span_sc.set_attribute("self_consistency.k", k)
    _span_sc.set_attribute("self_consistency.valid_samples", len(valid_samples))
    _span_sc.set_attribute("self_consistency.agreement", agreement)
    _span_sc.end()

    logger.info(
        "self_consistency.completed",
        k=k,
        valid=len(valid_samples),
        agreement=agreement,
    )

    if agreement > 0.8:
        # High agreement — proceed with best sample
        best = _pick_best_sample(valid_samples)
        intent_dict: dict[str, Any] = {
            "intent": best.get("primary_goal", ""),
            "parameters": best.get("known_parameters", {}),
        }
        missing_slots = [s.get("name", "") for s in best.get("missing_info_slots", [])]

        return {
            "intent_analysis": best,
            "intent": intent_dict,
            "missing_info_slots": missing_slots,
            "self_consistency_samples": sample_data,
            "response_type": best.get("response_type", "tool"),
            "_routing_decision": "proceed",
            "confidence": best.get("confidence", 0.5),
        }

    # Low agreement — ask for clarification
    goals = [s.get("primary_goal", "") for s in valid_samples[:3]]
    question = (
        f"I see a few possible interpretations of your request: "
        f"{' or '.join(f'\"{g}\"' for g in set(goals) if g)}. "
        f"Could you clarify which one you meant?"
    )

    return {
        "final_response": question,
        "self_consistency_samples": sample_data,
        "_routing_decision": "ask",
    }
