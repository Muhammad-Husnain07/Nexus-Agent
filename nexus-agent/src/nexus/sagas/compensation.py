"""Compensation engine — saga-style rollback of completed side effects.

When a workflow fails beyond the retry/quorum limits, already-succeeded
side-effectful operations should be compensated (undone) where a
``compensating_operation`` is declared on the tool metadata. Compensation
is BEST-EFFORT: every attempt is recorded in ``compensation_log`` for audit,
and failures are logged rather than blocking shutdown.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select

from nexus.db.base import async_session as _async_session
from nexus.db.models.compensation_log import CompensationLog

logger = structlog.get_logger("nexus.sagas.compensation")


class CompensationService:
    """Executes compensating operations for succeeded tools after failure."""

    async def compensate(
        self,
        session_id: str | None,
        succeeded_tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Run compensation for each succeeded tool that declares one.

        Args:
            session_id: Originating session id.
            succeeded_tools: List of ``{tool_name, tool_id, inputs, result}``
                for tools that completed BEFORE the failure.

        Returns:
            List of compensation records (for audit/tests).
        """
        records: list[dict[str, Any]] = []
        for item in succeeded_tools:
            tool_name = item.get("tool_name", "")
            tool_id = item.get("tool_id")
            inputs = item.get("inputs", {})
            comp_op = await self._lookup_compensating_operation(tool_name, tool_id)
            if not comp_op:
                continue
            record = await self._run_compensation(
                session_id=session_id,
                tool_name=tool_name,
                tool_id=tool_id,
                comp_op=comp_op,
                inputs=inputs,
            )
            records.append(record)
        return records

    async def _lookup_compensating_operation(
        self,
        tool_name: str,
        tool_id: Any,
    ) -> str | None:
        """Read ``compensating_operation`` metadata from the Tool registry."""
        try:
            from sqlalchemy import select as _t_select

            from nexus.db.models.tool import Tool

            async with _async_session() as session:
                stmt = _t_select(Tool.compensating_operation).where(Tool.name == tool_name)
                result = await session.execute(stmt)
                return result.scalar_one_or_none()
        except Exception as exc:
            logger.warning("compensation.metadata_lookup_failed", tool=tool_name, error=str(exc)[:200])
            return None

    async def _run_compensation(
        self,
        session_id: str | None,
        tool_name: str,
        tool_id: Any,
        comp_op: str,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute the compensating operation via the ToolExecutor (best-effort)."""
        record_id = uuid.uuid4()
        try:
            async with _async_session() as session:
                session.add(CompensationLog(
                    id=record_id,
                    session_id=session_id,
                    original_tool=tool_name,
                    original_tool_id=uuid.UUID(str(tool_id)) if tool_id else None,
                    compensating_operation=comp_op,
                    input_payload=inputs,
                    status="pending",
                ))
                await session.commit()

            # Execute the compensating tool
            from nexus.execution.context import ExecutionContext as _ExecCtx
            from nexus.tools.executor import ToolExecutor

            executor = ToolExecutor()
            from nexus.tools.registry import ToolRegistry

            registry = ToolRegistry()
            comp_tool = await registry.get_by_name(comp_op)
            if comp_tool is None:
                raise ValueError(f"Compensating operation '{comp_op}' not registered")

            outcome = await executor.execute(
                tool=comp_tool,
                inputs=inputs,
                context=_ExecCtx(session_id=session_id or "", agent_run_id=None),
                session=None,
                skip_approval=True,
            )
            status = "success" if outcome.status == "success" else "failed"
            error = None if status == "success" else outcome.error

            async with _async_session() as session:
                result = await session.execute(
                    select(CompensationLog).where(CompensationLog.id == record_id)
                )
                row = result.scalar_one_or_none()
                if row is not None:
                    row.status = status
                    row.error_message = error
                    row.completed_at = datetime.now(UTC)
                    await session.commit()

            logger.info(
                "compensation.executed",
                tool=tool_name,
                operation=comp_op,
                status=status,
            )
            return {"id": str(record_id), "tool": tool_name, "operation": comp_op, "status": status}

        except Exception as exc:
            logger.warning(
                "compensation.failed",
                tool=tool_name,
                operation=comp_op,
                error=str(exc)[:300],
            )
            try:
                async with _async_session() as session:
                    result = await session.execute(
                        select(CompensationLog).where(CompensationLog.id == record_id)
                    )
                    row = result.scalar_one_or_none()
                    if row is not None:
                        row.status = "failed"
                        row.error_message = str(exc)[:500]
                        row.completed_at = datetime.now(UTC)
                        await session.commit()
            except Exception:
                pass
            return {"id": str(record_id), "tool": tool_name, "operation": comp_op, "status": "failed"}
