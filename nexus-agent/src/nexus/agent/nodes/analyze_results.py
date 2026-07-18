"""analyze_results node — review tool results and decide next action."""

from __future__ import annotations

import json
from typing import Any

import structlog

from nexus.agent.prompts import prompt_manager
from nexus.agent.state import AgentState, AnalysisResult
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.agent.nodes.analyze_results")


def _openai_message(role: str, content: str, **kwargs: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": role, "content": content}
    msg.update(kwargs)
    return msg


async def analyze_results(
    state: AgentState,
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Review tool results and decide the next action.

    For *every* completed step (success or failure), invokes the LLM to
    evaluate whether the outcome matched the expected outcome, then decides:
    - continue (advance to next step)
    - revise (regenerate remaining plan)
    - clarify (ask user for more info)
    - preview (show intermediate result for user approval before continuing)
    - escalate (surface error to user)
    - finalize (plan complete)

    The ``escalate`` action maps to ``"ask"`` in the routing layer.

    Returns:
        Dict with ``_routing_decision``, optionally updated ``plan``,
        ``current_step_index``, and ``analysis_result``.
    """
    plan: list[dict[str, Any]] | None = state.get("plan")
    step: dict[str, Any] | None = _get_current_step(state)
    decision: str = "finalize"

    if plan and step is not None:
        idx: int = state.get("current_step_index", 0)
        next_idx: int = idx + 1

        deps = step.get("depends_on", [])
        deps_met = all(any(p["id"] == dep and p["status"] == "done" for p in plan) for dep in deps)

        if not deps_met:
            decision = "continue"
        else:
            step_description = step.get("description", "")
            expected_outcome = step.get("expected_outcome", "")
            step_status = step.get("status", "done")
            tool_results_list = state.get("tool_results") or []
            tool_result_data = json.dumps(
                (tool_results_list[-1] if tool_results_list else {}).get("data", "no data"), indent=2
            )
            last_result = tool_results_list[-1] if tool_results_list else {}

            # Shortcut: if step succeeded and no more steps remain, finalize
            if step_status == "done" and next_idx >= len(plan) and last_result.get("status") == "success":
                logger.info("analyze.success_finalize", step=idx)
                step["status"] = "done"
                plan[idx] = step
                return {
                    "plan": plan,
                    "_routing_decision": "finalize",
                    "analysis_result": {"decision": "finalize"},
                }

            system_prompt = prompt_manager.render(
                "analyze_results",
                version="2.0",
                step_description=step_description,
                expected_outcome=expected_outcome,
                tool_result=tool_result_data,
            )

            extra_context = (
                f"\n\n**Current step status:** {step_status}\n"
                f"**Steps remaining:** {max(0, len(plan) - idx - 1)}\n"
                f"**Plan length:** {len(plan)}"
            )

            response = await llm.complete(
                model=model,
                messages=[
                    _openai_message("system", system_prompt + extra_context),
                    _openai_message(
                        "user",
                        f"Evaluate step '{step_description}' (status: {step_status}). "
                        f"Expected: {expected_outcome or 'not specified'}. "
                        f"Result: {tool_result_data[:200]}",
                    ),
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )

            try:
                parsed: dict[str, Any] = json.loads(response.content or "{}")
                analysis = AnalysisResult(**parsed)
                decision = _map_next_action(analysis.next_action, next_idx, len(plan))
            except Exception as exc:
                logger.warning("analyze.parse_failed", error=str(exc))
                # Fallback: auto-advance if done, finalize otherwise
                if step_status == "done" and next_idx < len(plan):
                    step["status"] = "done"
                    plan[idx] = step
                    decision = "continue"
                    return {
                        "plan": plan,
                        "current_step_index": next_idx,
                        "_routing_decision": "continue",
                        "analysis_result": {"decision": "continue", "reasoning": "parse fallback"},
                    }
                decision = "finalize"

    # Execute the decision
    if decision == "continue" and plan and step and next_idx < len(plan):
        step["status"] = "done"
        plan[idx] = step
        logger.info("analyze.advancing", next_step=next_idx, plan_length=len(plan))
        return {
            "plan": plan,
            "current_step_index": next_idx,
            "_routing_decision": "continue",
            "analysis_result": {"decision": "continue"},
        }

    logger.info("analyze.decision", decision=decision)
    return {"_routing_decision": decision, "analysis_result": {"decision": decision}}


def _get_current_step(state: AgentState) -> dict[str, Any] | None:
    plan: list[dict[str, Any]] | None = state.get("plan")
    if not plan:
        return None
    idx: int = state.get("current_step_index", 0)
    if 0 <= idx < len(plan):
        return plan[idx]
    return None


def _map_next_action(next_action: str, next_idx: int, plan_len: int) -> str:
    """Map AnalysisResult.next_action to routing decision string."""
    mapping = {
        "continue": "continue",
        "revise": "revise",
        "clarify": "ask",
        "escalate": "finalize",
        "preview": "preview",
        "finalize": "finalize",
    }
    decision = mapping.get(next_action, "finalize")
    # Guard: don't continue if no steps remain
    if decision == "continue" and next_idx >= plan_len:
        return "finalize"
    return decision
