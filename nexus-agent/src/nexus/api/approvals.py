"""HITL approval management — approve/reject pending tool actions + recovery.

Endpoints:
- ``POST /api/v1/sessions/{session_id}/approve`` — approve pending tools
- ``POST /api/v1/sessions/{session_id}/reject`` — reject pending tools
- ``POST /api/v1/sessions/{session_id}/recover`` — recover to a previous checkpoint
- ``POST /api/v1/sessions/{session_id}/recover/{node_name}`` — recover before a specific node

No hardcoded tool names. Approval decisions are injected into the graph
checkpointer state. Recovery uses LangGraph's state history to find the
appropriate checkpoint — fully dynamic, supports any node in the graph.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nexus.api.dependencies import AgentRunnerDep
from nexus.agent.runner import AgentRunner

logger = structlog.get_logger("nexus.api.approvals")


class RecoverResponse(BaseModel):
    status: str
    session_id: str
    recovered_to: str | None = None
    message_count: int = 0

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


@router.post("/{session_id}/recover", status_code=200)
async def recover_session(
    session_id: str,
    runner: AgentRunnerDep,
) -> RecoverResponse:
    """Recover the graph to the last available checkpoint.

    Queries LangGraph's state history and restores to the penultimate
    checkpoint (skipping the final terminal state). Returns the recovered
    state metadata.

    Fully dynamic — works with any graph topology.
    """
    sid = str(session_id)

    try:
        recovered = await runner.recover(sid, target_node=None)
        if not recovered:
            raise HTTPException(status_code=404, detail="No checkpoint found for this session")

        state = recovered.get("state", {})
        msg_count = len(state.get("messages", []))

        logger.info("recovery.completed", session_id=sid, message_count=msg_count)

        return RecoverResponse(
            status="recovered",
            session_id=sid,
            recovered_to="last",
            message_count=msg_count,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("recovery.failed", session_id=sid, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Recovery failed: {exc}")


@router.post("/{session_id}/recover/{node_name}", status_code=200)
async def recover_session_to_node(
    session_id: str,
    node_name: str,
    runner: AgentRunnerDep,
) -> RecoverResponse:
    """Recover the graph to the checkpoint before a specific node.

    Finds the checkpoint in LangGraph's state history where ``node_name``
    was about to execute, and restores to that point. Supports any node
    in the graph without hardcoding.

    Example: ``POST /sessions/{id}/recover/ExecutorNode`` restores to
    the state right before the executor ran.
    """
    sid = str(session_id)

    try:
        recovered = await runner.recover(sid, target_node=node_name)
        if not recovered:
            raise HTTPException(
                status_code=404,
                detail=f"No checkpoint found before '{node_name}' for this session",
            )

        state = recovered.get("state", {})
        msg_count = len(state.get("messages", []))

        logger.info("recovery.node_completed", session_id=sid, node=node_name, message_count=msg_count)

        return RecoverResponse(
            status="recovered",
            session_id=sid,
            recovered_to=node_name,
            message_count=msg_count,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("recovery.node_failed", session_id=sid, node=node_name, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Recovery to '{node_name}' failed: {exc}")
