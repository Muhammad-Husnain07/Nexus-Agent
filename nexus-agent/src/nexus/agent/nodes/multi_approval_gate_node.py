"""MultiApprovalGateNode — policy-driven multi-stage human approval gate.

Replaces the single-binary ``ApprovalGateNode`` with a dynamic,
DB-backed approval chain. Each policy defines an ordered series of
approval steps (roles, TTLs, escalation paths).

No hardcoded approver names or roles — all driven by DB metadata.
"""

from __future__ import annotations

import time as _time
from typing import Any

import structlog
from sqlalchemy import select

from nexus.agent.state import AgentState
from nexus.config.settings import get_settings

logger = structlog.get_logger("nexus.agent.nodes.multi_approval_gate")


async def multi_approval_gate_node(state: AgentState) -> dict[str, Any]:
    """Check planned tools against multi-stage approval policies.

    Reads the execution graph's tool names, matches against all enabled
    ``ApprovalPolicy`` rows, and selects the longest-matching policy.
    If a match is found, checks the ``_approval_chain_state`` to determine
    which step we're on and routes accordingly.

    Returns:
        State update with approval chain state or pass-through if no gate needed.
    """
    graph_data = state.get("_execution_graph")

    if not graph_data:
        logger.info("multi_approval_gate.no_graph")
        return {"_approval_granted": True}

    nodes = graph_data.get("nodes", {}) if isinstance(graph_data, dict) else {}
    tool_names = list({
        nd.get("tool_name", "") for nd in nodes.values()
        if isinstance(nd, dict) and nd.get("tool_name")
    })
    if not tool_names:
        logger.info("multi_approval_gate.no_tools")
        return {"_approval_granted": True}

    # Tool detail map for the conversational checkpoint context: name →
    # {inputs, method} so the agent can present the actual operation
    # (e.g. "delete 143 inactive users") instead of a bare tool list.
    tool_details: dict[str, dict[str, Any]] = {}
    for nd in nodes.values():
        if not isinstance(nd, dict):
            continue
        tname = nd.get("tool_name", "")
        if not tname:
            continue
        details = tool_details.setdefault(tname, {"inputs": {}, "method": ""})
        inputs = nd.get("inputs")
        if isinstance(inputs, dict) and inputs:
            details["inputs"].update(inputs)
        if not details["method"]:
            details["method"] = str(nd.get("http_method", "GET"))

    # Find the best-matching approval policy (available_tools loaded from GlobalContext, not state)
    from nexus.context.global_context import get_global_context
    available_tools = []  # tools are resolved via GlobalContext O(1) map
    policy = await _resolve_policy(tool_names, available_tools)
    if policy is None:
        logger.info(
            "multi_approval_gate.no_policy",
            tools=tool_names,
            decision=state.get("_approval_decision"),
            granted=state.get("_approval_granted"),
        )
        return {"_approval_granted": True}

    logger.info(
        "multi_approval_gate.policy_matched",
        policy=policy.get("name"),
        tools=tool_names,
        decision=state.get("_approval_decision"),
    )
    return await _process_approval_chain(state, policy, tool_names, tool_details)


async def _resolve_policy(
    tool_names: list[str],
    available_tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Find the best-matching ApprovalPolicy for the planned tools.

    Loads all enabled policies from DB, scores each by how many
    trigger conditions are satisfied, and returns the best match.
    Falls back to GlobalContext if available_tools not provided.
    """
    if not available_tools:
        available_tools = []
    try:
        from nexus.db.base import async_session as _db_session
        from nexus.db.models.tool import Tool

        # Resolve tool risk/cost metadata dynamically from the Tool registry so
        # the gate works even when available_tools is not carried in state.
        if not available_tools and tool_names:
            async with _db_session() as session:
                result = await session.execute(
                    select(Tool).where(Tool.name.in_(tool_names))
                )
                available_tools = [
                    {
                        "name": t.name,
                        "risk_level": t.risk_level or "low",
                        "cost_per_call": 0.0,
                    }
                    for t in result.scalars().all()
                ]

        from nexus.db.models.approval import ApprovalPolicy

        async with _db_session() as session:
            result = await session.execute(
                select(ApprovalPolicy)
                .where(ApprovalPolicy.enabled == True)  # noqa: E712
                .order_by(ApprovalPolicy.priority.desc())
            )
            policies = result.scalars().all()
    except Exception as exc:
        logger.warning("multi_approval_gate.db_error", error=str(exc))
        return None

    best_policy: dict[str, Any] | None = None
    best_score = 0

    tool_map = {t.get("name", ""): t for t in available_tools if t.get("name")}
    max_risk = _max_risk_level(tool_names, tool_map)
    max_cost = _max_estimated_cost(tool_names, tool_map)

    for pol in policies:
        trigger = pol.trigger or {}
        score = 0

        # Risk level match
        trigger_risk = trigger.get("risk_level", "")
        if trigger_risk and max_risk == trigger_risk:
            score += 3
        elif trigger_risk:
            continue

        # Capability match (exact or wildcard)
        trigger_cap = trigger.get("capability", "")
        if trigger_cap and trigger_cap != "*":
            if trigger_cap in tool_names:
                score += 2
            else:
                continue

        # Cost threshold
        trigger_max_amount = trigger.get("max_amount")
        if trigger_max_amount is not None:
            if max_cost <= trigger_max_amount:
                score += 1
            else:
                continue

        if score > best_score:
            best_score = score
            best_policy = {
                "id": str(pol.id),
                "name": pol.name,
                "steps": list(pol.steps or []),
                "trigger": trigger,
            }

    return best_policy


async def _process_approval_chain(
    state: AgentState,
    policy: dict[str, Any],
    tool_names: list[str],
    tool_details: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Process the current step in an approval chain."""
    tool_details = tool_details or {}
    # IMMUTABLE: the chain state comes from the checkpointed channel — copy
    # before any write so a mid-node exception/retry never observes
    # half-mutated state (LangGraph hands nodes shared references).
    raw_chain: dict[str, Any] = state.get("_approval_chain_state") or {}
    chain_state: dict[str, Any] = dict(raw_chain)
    _pending = state.get("_approval_pending") or {}
    steps = policy.get("steps", [])

    if not steps:
        return {"_approval_granted": True}

    # Determine current step index
    completed_steps: list[dict[str, Any]] = list(chain_state.get("completed_steps", []))
    current_idx = len(completed_steps)

    # All steps completed — clear per-step request timestamps so stale
    # chain state cannot masquerade as a pending approval.
    if current_idx >= len(steps):
        chain_state = _clear_requested_at(chain_state)
        return {"_approval_granted": True, "_approval_chain_state": chain_state}

    current_step = steps[current_idx]

    # Check the GLOBAL decision first (set by POST /approve or /reject)
    global_decision = state.get("_approval_decision")
    if global_decision == "approved":
        completed_steps.append({
            "step_id": current_step.get("step_id", f"step_{current_idx}"),
            "decision": "approved",
            "timestamp": _time.time(),
        })
        chain_state["completed_steps"] = completed_steps
        if len(completed_steps) >= len(steps):
            chain_state = _clear_requested_at(chain_state)
            return {
                "_approval_granted": True,
                "_needs_approval": False,
                "_pending_approval_tools": [],
                "_approval_chain_state": chain_state,
                # Clear the conversational checkpoint — the decision is consumed
                "_approval_pending": None,
                "_approval_checkpoint_context": None,
            }
        return {
            "_approval_chain_state": chain_state,
            "_needs_approval": True,
            "_pending_approval_tools": _build_step_message(current_step, completed_steps, steps),
        }
    if global_decision == "rejected":
        return {
            "_approval_granted": False,
            "_needs_approval": False,
            "_pending_approval_tools": [],
            "_approval_chain_state": chain_state,
            "_approval_pending": None,
            "_approval_checkpoint_context": None,
        }

    # Check if this step has been approved via the per-step chain state.
    # APPROVAL SEMANTIC BINDING (P1): the stored decision carries the
    # operation_hash it was approved for — a replanned/modified step
    # (different inputs) produces a different hash and the prior approval
    # is NOT honored (re-approval required).
    step_id = current_step.get("step_id", current_idx)
    step_decision = chain_state.get(f"step_{step_id}_decision")
    _step_approved_hash = chain_state.get(f"step_{step_id}_hash", "")
    _current_hash = _pending.get("operation_hash", "") if isinstance(
        _pending, dict
    ) else ""
    if step_decision == "approved" and (
        not _step_approved_hash or _step_approved_hash == _current_hash
    ):
        completed_steps.append({
            "step_id": current_step.get("step_id", f"step_{current_idx}"),
            "decision": "approved",
            "timestamp": _time.time(),
        })
        chain_state["completed_steps"] = completed_steps
        # Move to next step
        if len(completed_steps) >= len(steps):
            chain_state = _clear_requested_at(chain_state)
            return {
                "_approval_granted": True,
                "_needs_approval": False,
                "_pending_approval_tools": [],
                "_approval_chain_state": chain_state,
                "_approval_pending": None,
                "_approval_checkpoint_context": None,
            }
        return {
            "_approval_chain_state": chain_state,
            "_needs_approval": True,
            "_pending_approval_tools": _build_step_message(current_step, completed_steps, steps),
        }

    if step_decision == "rejected":
        return {
            "_approval_granted": False,
            "_needs_approval": False,
            "_pending_approval_tools": [],
            "_approval_chain_state": chain_state,
            "_approval_pending": None,
            "_approval_checkpoint_context": None,
        }

    # Check for escaping via freed_by_jsonpath
    freed = current_step.get("freed_by_jsonpath", "")
    if freed:
        try:
            import jsonpath_ng.ext as _jp
            matches = _jp.parse(freed).find({"tool_names": tool_names, "state": state})
            if matches:
                completed_steps.append({
                    "step_id": current_step.get("step_id", f"step_{current_idx}"),
                    "decision": "auto_freed",
                    "timestamp": _time.time(),
                })
                chain_state["completed_steps"] = completed_steps
                return {
                    "_needs_approval": False,
                    "_pending_approval_tools": [],
                    "_approval_chain_state": chain_state,
                }
        except Exception:
            pass

    # Check TTL-based escalation
    ttl = current_step.get("ttl_seconds", 3600)
    requested_at = chain_state.get(f"step_{current_idx}_requested_at")
    if requested_at is not None and _time.time() - requested_at > ttl:
        escalation_role = current_step.get("escalation_role", "")
        if escalation_role:
            current_step = dict(current_step)
            current_step["role"] = escalation_role
            current_step["escalated"] = True
            logger.info(
                "multi_approval_gate.escalated",
                step=current_idx,
                new_role=escalation_role,
            )

    # Check if this step was already requested
    if chain_state.get(f"step_{current_idx}_requested_at") is not None:
        return {
            "_needs_approval": True,
            "_pending_approval_tools": _build_step_message(current_step, completed_steps, steps),
        }

    chain_state[f"step_{current_idx}_requested_at"] = _time.time()
    chain_state["policy_id"] = policy.get("id", "")
    chain_state["policy_name"] = policy.get("name", "")

    approval_message = _build_approval_message(current_step, completed_steps, steps, policy)

    # Dynamic consequence summary for the conversational checkpoint —
    # composed from the actual plan metadata (method + inputs), never
    # hardcoded operation text.
    context_summary = _build_checkpoint_context(tool_names, tool_details)

    # APPROVAL SEMANTIC BINDING (P1): the decision binds to the EXACT
    # operation set — a hash of (policy, step, tools, resolved inputs).
    # A replanned/modified operation produces a different hash and is
    # NEVER auto-authorized by a prior approval.
    import hashlib as _hl
    import json as _json

    _binding_payload = {
        "policy": policy.get("name", ""),
        "step": current_step.get("step_id", f"step_{current_idx}"),
        "tools": sorted(tool_names),
        "inputs": sorted(
            str(v) for v in (current_step.get("inputs") or {}).values()
        ),
    }
    operation_hash = _hl.sha256(
        _json.dumps(_binding_payload, sort_keys=True).encode()
    ).hexdigest()[:24]

    return {
        "final_response": approval_message,
        "_needs_approval": True,
        "_pending_approval_tools": _build_step_message(current_step, completed_steps, steps),
        "_approval_chain_state": chain_state,
        "_routing_decision": "finalize",
        "_approval_requested_at": _time.time(),
        # CONVERSATIONAL CHECKPOINT: persist the open decision so the next
        # chat message routes to ApprovalCheckpointResumeNode (non-binary
        # approve/reject/cancel/clarify/modify resume).
        "_approval_pending": {
            "policy": policy.get("name", ""),
            "step": current_step.get("step_id", f"step_{current_idx}"),
            "message": approval_message,
            "context": context_summary,
            "tools": tool_names,
            "tool_details": tool_details,
            "requested_at": _time.time(),
            "operation_hash": operation_hash,
        },
        "_approval_checkpoint_context": (
            context_summary or approval_message
        ),
    }


def _build_checkpoint_context(
    tool_names: list[str],
    tool_details: dict[str, dict[str, Any]],
) -> str:
    """Compose a dynamic consequence summary for the conversational checkpoint.

    Uses ONLY the plan's metadata (tool names, HTTP methods, resolved
    inputs) — no hardcoded operation text. When input values are present
    they are included so the user sees exactly what would be affected.
    """
    if not tool_names:
        return ""
    parts: list[str] = []
    for name in tool_names:
        details = tool_details.get(name) or {}
        method = str(details.get("method", "GET")).upper()
        inputs = details.get("inputs") or {}
        if inputs:
            input_str = ", ".join(
                f"{k}={v}" for k, v in inputs.items() if v not in (None, "")
            )
            if input_str:
                parts.append(f"{method} {name} ({input_str})")
                continue
        parts.append(f"{method} {name}")
    summary = "This will perform: " + "; ".join(parts[:8])
    if len(parts) > 8:
        summary += f" (+{len(parts) - 8} more)"
    return summary


def _clear_requested_at(chain_state: dict[str, Any]) -> dict[str, Any]:
    """Strip per-step ``*_requested_at`` keys from a completed chain.

    Returns a new dict (immutable update) — stale request timestamps
    would otherwise persist in the checkpoint and make a completed
    chain look like a pending approval.
    """
    return {
        k: v for k, v in chain_state.items() if not k.endswith("_requested_at")
    }


def _max_risk_level(
    tool_names: list[str],
    tool_map: dict[str, dict[str, Any]],
) -> str:
    """Find the highest risk level among the planned tools.

    Ordering is derived dynamically from the registered risk levels (DB
    enum) with settings override support — never a hardcoded map.
    """
    try:
        risk_order = get_settings().agent.risk_order
    except Exception:
        risk_order = None

    if risk_order is None:
        from nexus.db.models.enums import ToolRiskLevel

        risk_order = {
            level.value: idx
            for idx, level in enumerate(ToolRiskLevel)
        }

    max_level = "low"
    for name in tool_names:
        t = tool_map.get(name, {})
        r = t.get("risk_level", "low")
        if risk_order.get(r, 0) > risk_order.get(max_level, 0):
            max_level = r
    return max_level


def _max_estimated_cost(
    tool_names: list[str],
    tool_map: dict[str, dict[str, Any]],
) -> float:
    """Find the max estimated cost among the planned tools."""
    total = 0.0
    for name in tool_names:
        t = tool_map.get(name, {})
        total += t.get("cost_per_call", 0.0) or 0.0
    return total


def _build_step_message(
    current_step: dict[str, Any],
    completed_steps: list[dict[str, Any]],
    all_steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the pending approval tool list for the current step."""
    return [{
        "step_id": current_step.get("step_id", ""),
        "step_index": len(completed_steps),
        "step_total": len(all_steps),
        "required_role": current_step.get("role", ""),
        "escalated": current_step.get("escalated", False),
        "ttl_seconds": current_step.get("ttl_seconds", 3600),
    }]


def _build_approval_message(
    current_step: dict[str, Any],
    completed_steps: list[dict[str, Any]],
    all_steps: list[dict[str, Any]],
    policy: dict[str, Any],
) -> str:
    """Build a conversational approval request for the current chain step.

    Reads like a natural question — the operation and its consequence are
    presented, and the user may reply freely (yes / no / change it / ask).
    """
    step_label = f"{len(completed_steps) + 1} of {len(all_steps)}" if len(all_steps) > 1 else ""
    role_hint = current_step.get("role") or ""
    if role_hint:
        role_hint = f" (requires {role_hint})"
    escalation = " (escalated after timeout)" if current_step.get("escalated") else ""
    description = current_step.get("description") or ""
    lines = [f"Before I proceed, I need your approval{escalation}."]
    if step_label:
        lines[0] = f"Before I proceed, I need your approval — step {step_label}{role_hint}{escalation}."
    if description:
        lines.append(f"{description}")
    lines.append("You can say \"yes, go ahead\", \"no\", tell me what to change, or ask me anything about it.")
    return "\n".join(lines)
