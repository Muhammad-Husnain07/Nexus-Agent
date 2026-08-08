"""CronNode — scheduled recurring execution for long-running workflows.

Reads ``_long_running_workflow_id`` from state.  If the workflow has a
``schedule_cron`` expression, schedules the next run via Redis and
updates the workflow's ``next_run_at`` timestamp.

After scheduling, routes to the ExecutorNode for the current run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from nexus.agent.state import AgentState

logger = structlog.get_logger("nexus.agent.nodes.cron")


async def cron_node(state: AgentState) -> dict[str, Any]:
    """Schedule the next run for a long-running workflow and proceed.

    If the current session is associated with a ``LongRunningWorkflow``
    that has a ``schedule_cron``, computes the next run time and stores
    it so the scheduler picks it up.

    Returns:
        State update with scheduling info or pass-through.
    """
    workflow_id = state.get("_long_running_workflow_id")
    if workflow_id is None:
        return {"_cron_next": None}

    schedule_cron = state.get("_schedule_cron")
    if not schedule_cron:
        return {"_cron_next": None}

    try:
        from nexus.db.base import async_session as _db
        from nexus.db.models.long_running_workflow import LongRunningWorkflow
        from sqlalchemy import select

        async with _db() as session:
            result = await session.execute(
                select(LongRunningWorkflow).where(LongRunningWorkflow.id == workflow_id)
            )
            wf = result.scalar_one_or_none()
            if wf is None:
                return {"_cron_next": None}

            # Compute next run using cronsim
            next_run = _compute_next_cron(wf.schedule_cron)
            wf.next_run_at = next_run
            wf.run_count = (wf.run_count or 0) + 1
            wf.last_run_at = datetime.now(UTC)
            await session.commit()

            logger.info(
                "cron_node.scheduled",
                workflow_id=str(workflow_id),
                next_run=str(next_run) if next_run else None,
            )

            return {
                "_cron_next": str(next_run) if next_run else None,
                "_total_run_count": wf.run_count,
            }

    except Exception as exc:
        logger.warning("cron_node.schedule_failed", error=str(exc))
        return {"_cron_next": None}


def _compute_next_cron(expression: str | None) -> datetime | None:
    """Compute the next run time from a cron expression using cronsim.

    Falls back to +1 hour if cronsim is not available.
    """
    if not expression:
        return None

    now = datetime.now(UTC)

    try:
        from cronsim import croniter  # type: ignore[import-untyped]
        return croniter(expression, now).get_next(datetime)
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("cron_node.parse_failed", expression=expression, error=str(exc))

    return None
