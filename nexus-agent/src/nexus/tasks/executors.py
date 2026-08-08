"""Default task executors — registered at import time.

These executors are what the worker runs for each task type. Registration is
via ``register_executor`` (dynamic map, no hardcoded dispatch). Add new task
types by registering a new executor — no core changes.

The ``workflow_run`` executor consumes an immutable ``ExecutionRequest``
(background whole-run handoff) and writes back a typed ``ExecutionResult``
with a progress timeline — the worker owns the FULL graph (checkpoints,
artifacts, approvals, retries, recovery in one runtime).
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.tasks.worker import register_executor

logger = structlog.get_logger("nexus.tasks.executors")


async def workflow_run_executor(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute an agent run from an immutable ExecutionRequest.

    Payload (from the executor-node background handoff):
        execution_id / session_id / thread_id / message / *_version /
        registry_version / created_at   (ExecutionRequest.model_dump())
        _task_id                         (injected by the worker)
    """
    from datetime import datetime, timezone

    from nexus.execution.lifecycle import ExecutionRequest, ExecutionResult, ExecutionStatus

    task_id = str(payload.get("_task_id", ""))
    try:
        request = ExecutionRequest.model_validate(payload)
    except Exception as exc:
        raise ValueError(f"Invalid ExecutionRequest payload: {exc}") from exc

    from nexus.agent.runner import AgentRunner

    started = datetime.now(timezone.utc)
    runner = AgentRunner()
    progress_lines: list[str] = []
    events_out: list[dict[str, Any]] = []
    produced_artifacts: list[str] = []
    final_text = ""
    terminal_status = ExecutionStatus.COMPLETED

    async for event in runner.invoke(
        session_id=request.session_id,
        user_message=request.message,
    ):
        events_out.append({"type": event.type, "ts": event.ts, "payload": event.payload})
        if event.type == "step_progress":
            text = str((event.payload or {}).get("text", ""))
            if text:
                progress_lines.append(text)
        elif event.type == "artifact_produced":
            keys = (event.payload or {}).get("aggregated_keys") or []
            produced_artifacts.extend(str(k) for k in keys)
        elif event.type == "tool_call_completed":
            tool = str((event.payload or {}).get("tool_name", ""))
            if tool:
                produced_artifacts.append(tool)
        elif event.type == "final_response":
            final_text = str((event.payload or {}).get("text", ""))
        elif event.type == "error":
            progress_lines.append(f"Error: {str((event.payload or {}).get('message', ''))[:120]}")

    # Progress write-back (best-effort — the task row may be gone).
    try:
        from nexus.tasks.registry import TaskRegistry

        await TaskRegistry().update_progress(task_id, 100)
    except Exception as exc:
        logger.warning("workflow_run.progress_write_failed", error=str(exc)[:200])

    completed = datetime.now(timezone.utc)
    result = ExecutionResult(
        execution_id=request.execution_id,
        status=terminal_status,
        final_response=final_text,
        produced_artifacts=produced_artifacts,
        events=events_out,
        progress_lines=progress_lines,
        started_at=started.isoformat(),
        completed_at=completed.isoformat(),
        duration_ms=int((completed - started).total_seconds() * 1000),
    )
    return result.model_dump()


register_executor("workflow_run", workflow_run_executor)
