"""HITL approval management — approve/reject pending tool actions.

Endpoints:
- ``POST /api/v1/sessions/{session_id}/approve`` — approve pending tools
- ``POST /api/v1/sessions/{session_id}/reject`` — reject pending tools

No hardcoded tool names. Approval decisions are injected into the graph
checkpointer state. On next invoke, ``ApprovalGateNode`` reads the decision
and proceeds or rejects.

After injecting the decision, the endpoint calls ``runner.continue_after_approval()``
to re-trigger the graph from the existing checkpoint state, bypassing the router
and going directly to the approval gate.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException

from nexus.api.dependencies import AgentRunnerDep
from nexus.agent.runner import AgentRunner

logger = structlog.get_logger("nexus.api.approvals")

router = APIRouter(prefix="/sessions", tags=["approvals"])


@router.post("/{session_id}/approve", status_code=200)
async def approve_tools(
    session_id: str,
    runner: AgentRunnerDep,
) -> dict[str, str]:
    """Approve pending tool executions for a session.

    Injects ``_approval_decision: "approved"`` into the graph checkpointer
    state and re-triggers the graph. ``ApprovalGateNode`` reads the decision
    and allows high-risk tools to execute.
    """
    sid = str(session_id)

    try:
        graph = await runner._build_graph()
        config = {"configurable": {"thread_id": sid}}

        state = await graph.aget_state(config)
        if state is None or not state.values:
            raise HTTPException(status_code=404, detail="Session not found")

        # Inject approval decision and force_query_type to bypass router
        await graph.aupdate_state(config, {
            "_approval_decision": "approved",
            "_force_query_type": "single_tool",
        })

        # Re-trigger graph execution from the persisted state
        await runner.continue_after_approval(sid)

        logger.info("approval.approved", session_id=sid)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("approval.failed", session_id=sid, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to approve: {exc}")

    return {"status": "approved", "session_id": sid}


@router.post("/{session_id}/reject", status_code=200)
async def reject_tools(
    session_id: str,
    runner: AgentRunnerDep,
) -> dict[str, str]:
    """Reject pending tool executions for a session.

    Injects ``_approval_decision: "rejected"`` into the graph checkpointer
    state. The ``ApprovalGateNode`` will skip high-risk tools on next run.
    """
    sid = str(session_id)

    try:
        graph = await runner._build_graph()
        config = {"configurable": {"thread_id": sid}}

        state = await graph.aget_state(config)
        if state is None or not state.values:
            raise HTTPException(status_code=404, detail="Session not found")

        await graph.aupdate_state(config, {
            "_approval_decision": "rejected",
            "_force_query_type": "single_tool",
        })

        # Re-trigger graph execution
        await runner.continue_after_approval(sid)

        logger.info("approval.rejected", session_id=sid)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("approval.reject_failed", session_id=sid, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to reject: {exc}")

    return {"status": "rejected", "session_id": sid}
