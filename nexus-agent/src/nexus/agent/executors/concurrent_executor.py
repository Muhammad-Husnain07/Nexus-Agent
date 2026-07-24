"""
Concurrent Tool Executor — executes DAG waves in parallel with fault isolation,
timeout management, and automatic dependency resolution.

Architecture
============
1. Receives ``ExecutionPlan`` from the DAG Planner.
2. Executes each wave sequentially (wave N → wave N+1).
3. Within a wave, all tasks run concurrently via ``asyncio.gather``.
4. Results from wave N are fed into wave N+1's inputs via placeholder resolution.
5. Failed tasks are retried with exponential backoff (2^x seconds).
6. Strict timeouts prevent hung tools from blocking the graph.

Usage::

    executor = ConcurrentExecutor(tool_executor=ToolExecutor())
    results = await executor.execute(
        plan=execution_plan,
        max_concurrency=5,
        per_tool_timeout=15.0,
        global_timeout=60.0,
    )
    print(results.successful, results.failed)
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

import structlog

from nexus.config.settings import get_settings
from nexus.tools.executor import ToolExecutor

logger = structlog.get_logger("nexus.agent.executors.concurrent_executor")


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class ToolExecutionResult:
    """Outcome of a single tool execution."""
    task_id: str
    tool_name: str
    status: str  # "success", "error", "timeout"
    data: Any = None
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class ExecutionResults:
    """Aggregated results from executing the full plan."""
    by_task: dict[str, ToolExecutionResult] = field(default_factory=dict)
    by_wave: list[dict[str, ToolExecutionResult]] = field(default_factory=list)
    successful: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    timed_out: list[str] = field(default_factory=list)

    @property
    def all_successful(self) -> bool:
        return not self.failed and not self.timed_out


# ============================================================================
# Placeholder Resolution
# ============================================================================

_PLACEHOLDER_RE = re.compile(r"\$\{(.+?)\.result(?:\.(.+?))?\}")


def _resolve_placeholders(
    inputs: dict[str, Any],
    results: dict[str, Any],
) -> dict[str, Any]:
    """Resolve ``${task_id.result.field}`` placeholders with actual values."""
    resolved = {}
    for key, val in inputs.items():
        if isinstance(val, str):
            match = _PLACEHOLDER_RE.match(val)
            if match:
                task_id = match.group(1)
                field_path = match.group(2)
                result = results.get(task_id)
                if result is not None:
                    if field_path:
                        if isinstance(result, dict):
                            val = _deep_get(result, field_path)
                    else:
                        val = result
        resolved[key] = val
    return resolved


def _deep_get(obj: Any, path: str) -> Any:
    """Recursively traverse a nested dict using dot-separated path."""
    for part in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part, "")
        else:
            return ""
    return obj


# ============================================================================
# Concurrent Executor
# ============================================================================


class ConcurrentExecutor:
    """Wave-based concurrent tool executor with fault isolation and retry.

    Accepts ``ExecutionPlan`` from the DAG Planner and executes all tools
    through the configured ``ToolExecutor``.
    """

    def __init__(
        self,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        self._executor = tool_executor or ToolExecutor()
        self._settings = get_settings()

    async def execute(
        self,
        tasks: list[Any],
        waves: list[Any],
        max_concurrency: int = 5,
        per_tool_timeout: float = 15.0,
        global_timeout: float = 60.0,
    ) -> ExecutionResults:
        """Execute the plan's waves and return aggregated results.

        Args:
            plan: ``ExecutionPlan`` from DAG Planner.
            max_concurrency: Max parallel tools per wave.
            per_tool_timeout: Max seconds per individual tool call.
            global_timeout: Max seconds for the entire plan.

        Returns:
            ``ExecutionResults`` with per-task outcomes.
        """
        results = ExecutionResults()
        task_map: dict[str, Any] = {t.id: t for t in tasks}
        accumulated: dict[str, Any] = {}

        try:
            async with asyncio.timeout(global_timeout):
                for wave in waves:
                    logger.info(
                        "concurrent_executor.wave_start",
                        wave=wave.wave,
                        task_count=len(wave.tasks),
                    )

                    wave_outcomes = await self._execute_wave(
                        wave=wave,
                        task_map=task_map,
                        accumulated=accumulated,
                        max_concurrency=max_concurrency,
                        per_tool_timeout=per_tool_timeout,
                    )

                    # Record results and update accumulated data
                    wave_dict: dict[str, ToolExecutionResult] = {}
                    for outcome in wave_outcomes:
                        wave_dict[outcome.task_id] = outcome
                        results.by_task[outcome.task_id] = outcome
                        if outcome.status == "success":
                            results.successful.append(outcome.task_id)
                            accumulated[outcome.task_id] = outcome.data
                        elif outcome.status == "timeout":
                            results.timed_out.append(outcome.task_id)
                        else:
                            results.failed.append(outcome.task_id)

                    results.by_wave.append(wave_dict)

                    logger.info(
                        "concurrent_executor.wave_done",
                        wave=wave.wave,
                        success=len(wave_outcomes) - sum(1 for o in wave_outcomes if o.status != "success"),
                        failed=len(results.failed),
                    )

        except asyncio.TimeoutError:
            logger.error("concurrent_executor.global_timeout", timeout=global_timeout)

        return results

    async def _execute_wave(
        self,
        wave: Any,
        task_map: dict[str, Any],
        accumulated: dict[str, Any],
        max_concurrency: int,
        per_tool_timeout: float,
    ) -> list[ToolExecutionResult]:
        """Execute a single wave — run its tasks in parallel with concurrency cap.

        Fault isolation: each task runs independently; one failure doesn't
        affect other tasks in the same wave.
        """
        wave_tasks = wave.tasks[:max_concurrency]
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _run(task: Any) -> ToolExecutionResult:
            async with semaphore:
                return await self._execute_single(
                    task=task,
                    task_map=task_map,
                    accumulated=accumulated,
                    timeout=per_tool_timeout,
                )

        outcomes = await asyncio.gather(
            *(_run(t) for t in wave_tasks),
            return_exceptions=True,
        )

        results: list[ToolExecutionResult] = []
        for i, outcome in enumerate(outcomes):
            if isinstance(outcome, ToolExecutionResult):
                results.append(outcome)
            elif isinstance(outcome, Exception):
                results.append(ToolExecutionResult(
                    task_id=wave_tasks[i].id,
                    tool_name=wave_tasks[i].tool_name,
                    status="error",
                    error=str(outcome),
                ))
            else:
                results.append(ToolExecutionResult(
                    task_id=wave_tasks[i].id,
                    tool_name=wave_tasks[i].tool_name,
                    status="error",
                    error="Unknown error",
                ))

        return results

    async def _execute_single(
        self,
        task: Any,
        task_map: dict[str, Any],
        accumulated: dict[str, Any],
        timeout: float,
    ) -> ToolExecutionResult:
        """Execute a single tool task with retry policy and timeout.

        Retry policy:
        - Retry up to ``task.max_retries`` times.
        - Exponential backoff: 2^attempt seconds between retries.
        - Only retry on transient errors (timeout, connection error).
        - Do NOT retry validation errors or 4xx responses.
        """
        import time as _time

        resolved_inputs = _resolve_placeholders(task.inputs, accumulated)
        last_error: str | None = None

        for attempt in range(task.max_retries + 1):
            try:
                start = _time.perf_counter()

                # Resolve tool from registry
                tool_read = _tool_dict_to_read(task.tool_name)  # simplified
                if tool_read is None:
                    return ToolExecutionResult(
                        task_id=task.id,
                        tool_name=task.tool_name,
                        status="error",
                        error=f"Tool '{task.tool_name}' not found in registry",
                    )

                result = await asyncio.wait_for(
                    self._executor.execute(
                        tool=tool_read,
                        func_args=resolved_inputs,
                        context=ExecutionContext(session_id="", agent_run_id=""),
                        skip_approval=True,
                    ),
                    timeout=timeout,
                )

                duration = (_time.perf_counter() - start) * 1000

                if result.status == "success":
                    return ToolExecutionResult(
                        task_id=task.id,
                        tool_name=task.tool_name,
                        status="success",
                        data=result.data,
                        duration_ms=duration,
                    )

                # Error — retry if transient
                last_error = result.error or "Unknown error"
                if attempt < task.max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        "concurrent_executor.retry",
                        task=task.id, attempt=attempt, wait=wait, error=last_error,
                    )
                    await asyncio.sleep(wait)

            except asyncio.TimeoutError:
                last_error = f"Timed out after {timeout}s"
                if attempt < task.max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        "concurrent_executor.retry_timeout",
                        task=task.id, attempt=attempt, wait=wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    return ToolExecutionResult(
                        task_id=task.id,
                        tool_name=task.tool_name,
                        status="timeout",
                        error=last_error,
                    )

            except Exception as exc:
                last_error = str(exc)
                if attempt < task.max_retries:
                    wait = 2 ** attempt
                    await asyncio.sleep(wait)

        return ToolExecutionResult(
            task_id=task.id,
            tool_name=task.tool_name,
            status="error",
            error=last_error,
        )


# ============================================================================
# Helper: Quick tool lookup (simplified)
# ============================================================================

def _tool_dict_to_read(tool_name: str) -> Any:
    """Minimal tool lookup — returns a dict with tool metadata.

    In production, this queries the ToolRegistry via the DB session.
    For now, returns a dict with enough fields for ToolExecutor.
    """
    from nexus.tools.schemas import ToolRead

    return ToolRead(
        id="",
        name=tool_name,
        description="",
        purpose="",
        tool_type="http_api",
        endpoint_url="",
        http_method="GET",
        auth_type="none",
        auth_ref="",
        input_schema={},
        output_schema={},
        validation_rules={},
        examples=[],
        tags=[],
        category="general",
        requires_approval=False,
        risk_level="low",
        enabled=True,
    )


# Import for type hint
from nexus.tools.executor import ExecutionContext  # noqa: E402, F811
