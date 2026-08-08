"""ApprovalCheckpointResumeNode — conversational approval checkpoints.

When the ApprovalGate pauses for a decision, the checkpoint message is
returned in-chat. The user's NEXT message is classified here:

- approve  → decision=approved → resume graph from the checkpoint
- reject   → decision=rejected  → finalize with decline message
- cancel   → cancel the pending operation / active workflow
- clarify  → answer the question, stay paused
- modify   → extract the modification, replan the remaining steps, resume

The approval is NON-BINARY: a user may alter the request instead of simply
approving/rejecting. The gate consumes ``_approval_decision`` on resume; a
modification updates the collected workflow inputs so the replanned graph
reflects the change.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from nexus.agent.node_wrapper import context_node
from nexus.execution.context import ExecutionContext, StatePatch
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.agent.nodes.approval_checkpoint_resume")


@context_node
async def approval_checkpoint_resume_node(
    ctx: ExecutionContext,
    llm: LLMClient,
    model: str,
) -> StatePatch:
    """Classify the user's reply to an open approval checkpoint."""
    snapshot = ctx.snapshot
    pending = snapshot.get("_approval_pending") or {}
    user_msg = _last_user_message(snapshot)

    if not pending or not user_msg:
        # Nothing pending — fall through to the router
        return StatePatch(version=ctx.version + 1, updates={})

    intent = await _classify_approval_reply(llm, model, user_msg, pending)

    if intent == "approve":
        logger.info("approval_checkpoint.approved")
        # APPROVAL SEMANTIC BINDING (P1): record the operation hash the
        # approval binds to — the gate honors the stored approval ONLY for
        # the identical operation (a modified/replanned step re-approves).
        _chain = dict(snapshot.get("_approval_chain_state") or {})
        _step_id = str(pending.get("step") or "step_0")
        _hash = str(pending.get("operation_hash") or "")
        if _hash:
            _chain[f"step_{_step_id}_hash"] = _hash
        return StatePatch(version=ctx.version + 1, updates={
            "_approval_decision": "approved",
            "_approval_pending": None,
            "_approval_checkpoint_context": None,
            "_approval_modification": None,
            "_needs_approval": False,
            "_route_to_gate": True,
            "_routing_decision": "resume",
            "_approval_chain_state": _chain,
        })

    if intent == "reject":
        logger.info("approval_checkpoint.rejected")
        # Documented rule: a denial terminates the requested action UNLESS the
        # denied step is a required dependency whose removal still permits the
        # planner to satisfy the broader goal — only then do we replan.
        denied = _checkpoint_denied_tools(ctx.snapshot)
        blocks = False
        if denied:
            blocks = _denial_blocks_graph(
                ctx.snapshot.get("_execution_graph"),
                denied,
            )
        if blocks:
            logger.warning("approval_checkpoint.reject_blocks_graph", denied=sorted(denied))
            return StatePatch(version=ctx.version + 1, updates={
                "_approval_decision": "rejected",
                "_approval_pending": None,
                "_approval_checkpoint_context": None,
                "_approval_modification": None,
                "_needs_approval": False,
                "_routing_decision": "replan",
                "_replan_context": {
                    "completed_tools": [],
                    "unavailable_ops": sorted(denied),
                },
                "final_response": (
                    "Understood — the operation was not approved. "
                    "I'll find another way to complete the rest."
                ),
                "response_type": "replan",
            })
        return StatePatch(version=ctx.version + 1, updates={
            "_approval_decision": "rejected",
            "_approval_pending": None,
            "_approval_checkpoint_context": None,
            "_approval_modification": None,
            "_needs_approval": False,
            "_routing_decision": "finalize",
            "final_response": "Understood — the operation was not approved.",
            "response_type": "cancellation",
        })

    if intent == "cancel":
        logger.info("approval_checkpoint.cancelled")
        updates: dict[str, Any] = {
            "_approval_decision": "rejected",
            "_approval_pending": None,
            "_approval_checkpoint_context": None,
            "_approval_modification": None,
            "_needs_approval": False,
            "_routing_decision": "finalize",
            "final_response": "Cancelled — nothing was executed.",
            "response_type": "cancellation",
        }
        # Cancel any active workflow too
        if snapshot.get("_active_workflow_id"):
            updates["_active_workflow_id"] = None
        return StatePatch(version=ctx.version + 1, updates=updates)

    if intent == "modify":
        modification = await _extract_modification(llm, model, user_msg, pending)
        logger.info(
            "approval_checkpoint.modified",
            modification=(modification or "")[:200],
        )
        updates = {
            "_approval_modification": modification,
            "_approval_pending": None,
            "_approval_checkpoint_context": None,
            # Re-plan with the modified request — the router will re-plan
            # the remaining workflow steps from the updated intent.
            "_workflow_dynamic_intent": modification,
            "_route_to_planner": True,
            "_bypass_workflow": True,
            "_routing_decision": "resume",
        }
        return StatePatch(version=ctx.version + 1, updates=updates)

    # clarify — answer the user's question and stay paused
    answer = await _answer_question(llm, model, user_msg, pending)
    return StatePatch(version=ctx.version + 1, updates={
        "final_response": answer,
        "_routing_decision": "finalize",
        "response_type": "clarification",
        "_approval_checkpoint_context": pending.get("message", ""),
    })


# ============================================================================
# Helpers
# ============================================================================


def _last_user_message(snapshot: dict[str, Any]) -> str:
    messages: list = list(snapshot.get("messages", []))
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            return str(m.get("content", ""))
    return ""


def _checkpoint_denied_tools(snapshot: dict[str, Any]) -> set[str]:
    """Tools named in the pending approval checkpoint (the denied set)."""
    checkpoint = snapshot.get("_approval_checkpoint") or {}
    tools = checkpoint.get("tools") if isinstance(checkpoint, dict) else None
    return {str(t) for t in (tools or []) if t}


def _denial_blocks_graph(graph: dict[str, Any] | None, denied: set[str]) -> bool:
    """Deterministic check: does ANY surviving node depend on a denied tool?

    Follows both dependency signals: id-based ``depends_on`` edges and
    ``${<ref>.result}`` input placeholders (symbolic refs). A denial only
    triggers replanning when it blocks the remaining graph (documented rule).
    """
    if not graph or not denied:
        return False
    nodes = graph.get("nodes", {}) or {}
    id_tool: dict[str, str] = {}
    ref_tool: dict[str, str] = {}
    for nid, ndata in nodes.items():
        if not isinstance(ndata, dict):
            continue
        tool = str(ndata.get("tool_name") or ndata.get("capability") or "")
        id_tool[str(nid)] = tool
        ref = ndata.get("symbolic_ref")
        if ref:
            ref_tool[str(ref)] = tool

    def _tool_of(ref_or_id: str) -> str:
        return id_tool.get(ref_or_id) or ref_tool.get(ref_or_id) or ""

    for nid, ndata in nodes.items():
        if not isinstance(ndata, dict):
            continue
        if id_tool.get(str(nid), "") in denied:
            continue
        for dep in (ndata.get("depends_on") or []):
            if _tool_of(str(dep)) in denied:
                return True
        for value in (ndata.get("inputs") or {}).values():
            import re as _re

            for m in _re.finditer(r"\$\{([a-zA-Z0-9_]+)\.result", str(value)):
                if _tool_of(m.group(1)) in denied:
                    return True
    return False


# Conversational approval classification — FULLY LLM-DRIVEN. No phrase
# lists, no pattern sets, nothing hardcoded anywhere: the model reads the
# pending operation context and the user's reply, and decides the intent.
# This keeps the checkpoint open to any phrasing a user may use.

_VALID_INTENTS = ("approve", "reject", "cancel", "modify", "clarify")


async def _classify_approval_reply(
    llm: LLMClient,
    model: str,
    user_msg: str,
    pending: dict[str, Any],
) -> str:
    """Classify the user's reply into approve/reject/cancel/modify/clarify.

    Pure LLM classification — the model decides the intent from the pending
    operation context and the user's actual reply, so no phrasing is ever
    hardcoded. On any failure (provider outage, malformed response) the
    checkpoint stays paused with ``clarify`` — the user is asked again
    rather than guessing.
    """
    system_prompt = (
        "You are classifying a user's reply to an approval checkpoint. "
        "Return JSON with a single \"intent\" key: one of "
        "\"approve\", \"reject\", \"cancel\", \"modify\", or \"clarify\".\n"
        "- approve: user confirms the operation\n"
        "- reject: user declines the operation\n"
        "- cancel: user aborts the whole thing\n"
        "- modify: user changes the request instead of deciding (only X, use Y, exclude Z)\n"
        "- clarify: user asks a question about the operation\n"
        "Use the pending operation context and the user's exact reply to decide. "
        "When the reply is a yes/no about continuing, choose approve or reject.\n"
        "Only respond with the JSON object."
    )
    prompt = (
        f"Pending operation: {json.dumps(pending.get('message', ''))[:300]}\n"
        f"Consequences: {str(pending.get('context', ''))[:300]}\n"
        f"User reply: {user_msg[:500]}"
    )
    try:
        response = await llm.complete(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=64,
            response_format={"type": "json_object"},
        )
        if response.failed:
            logger.warning("approval_checkpoint.classify_llm_failed", error=response.error)
            return "clarify"
        content = response.content or ""
        data = json.loads(content)
        intent = str(data.get("intent", "clarify")).lower()
        if intent in _VALID_INTENTS:
            return intent
        return "clarify"
    except Exception as exc:
        logger.warning("approval_checkpoint.classify_failed", error=str(exc))
        return "clarify"


async def _extract_modification(
    llm: LLMClient,
    model: str,
    user_msg: str,
    pending: dict[str, Any],
) -> str:
    """Extract the user's modified request as a replanning prompt.

    When the LLM is unavailable (provider outage — observed with NVIDIA
    NIM), fall back to composing the modification from the pending
    operation's context plus the user's change, so the planner still
    receives a complete request instead of an ambiguous fragment.
    """
    original = pending.get("message", "") or ""
    context = pending.get("context", "") or ""
    fallback = f"{original} {context} User change: {user_msg}"
    system_prompt = (
        "You are extracting a MODIFIED request from a user's reply to an "
        "approval checkpoint. The user is changing what should be done. "
        "Return JSON with a single \"modification\" key containing a concise "
        "description of the new request (as if the user stated it fresh). "
        "Only respond with the JSON object."
    )
    prompt = (
        f"Original pending operation: {json.dumps(original)[:500]}\n"
        f"Consequences: {json.dumps(context)[:500]}\n"
        f"User's change: {user_msg[:500]}"
    )
    try:
        response = await llm.complete(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
        if response.failed:
            logger.warning("approval_checkpoint.extract_modification_failed", error=response.error)
            return fallback
        data = json.loads(response.content or "{}")
        mod = str(data.get("modification", "")).strip()
        return mod or fallback
    except Exception:
        return fallback


async def _answer_question(
    llm: LLMClient,
    model: str,
    user_msg: str,
    pending: dict[str, Any],
) -> str:
    """Answer a clarifying question about the pending operation."""
    system_prompt = (
        "Answer the user's question about the pending operation using ONLY "
        "the provided context. If you cannot answer, say so and restate the "
        "approval question. Be concise."
    )
    prompt = (
        f"Pending operation: {json.dumps(pending.get('message', ''))[:300]}\n"
        f"Consequences: {str(pending.get('context', ''))[:300]}\n"
        f"User question: {user_msg[:500]}"
    )
    try:
        response = await llm.complete(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=300,
        )
        if response.failed:
            return (
                "I don't have that detail yet. You can reply with "
                "'approve', 'reject', 'cancel', or describe a change."
            )
        return (response.content or "").strip() or (
            "I don't have that detail yet. You can reply with "
            "'approve', 'reject', 'cancel', or describe a change."
        )
    except Exception:
        return (
            "I don't have that detail yet. You can reply with "
            "'approve', 'reject', 'cancel', or describe a change."
        )
