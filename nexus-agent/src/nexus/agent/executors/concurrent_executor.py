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
import hashlib
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
    status: str  # "success", "error", "timeout", "uncertain"
    data: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    execution_key: str | None = None
    cached: bool = False
    attempt_id: int = 1
    idempotency_key: str | None = None


@dataclass
class ExecutionResults:
    """Aggregated results from executing the full plan."""
    by_task: dict[str, ToolExecutionResult] = field(default_factory=dict)
    by_wave: list[dict[str, ToolExecutionResult]] = field(default_factory=list)
    successful: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    timed_out: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def all_successful(self) -> bool:
        return not self.failed and not self.timed_out


@dataclass
class _WaveView:
    """Lightweight wave wrapper for pruned task lists."""
    wave: int
    tasks: list[Any]


# ============================================================================
# Placeholder Resolution
# ============================================================================

_PLACEHOLDER_RE = re.compile(r"\$\{(.+?)\.result(?:\[(\d+)\])?(?:\.(.+?))?\}")


def _get_field_aliases() -> dict[str, str]:
    """Load field name aliases from settings for cross-provider compatibility.

    When a step expects "latitude" but the tool returned "lat", these
    mappings ensure the placeholder is still resolved.  Configurable
    via ``NEXUS_TOOLS__FIELD_ALIASES`` environment variable.
    """
    try:
        from nexus.config.settings import get_settings
        return dict(get_settings().tools.field_aliases)
    except Exception:
        return {}


def _resolve_field(result_data: Any, field_name: str) -> Any:
    """Resolve a field from result data, trying aliases if the exact name fails."""
    aliases = _get_field_aliases()
    # Try exact match first (handles dict keys and object attributes)
    val = _deep_get(result_data, field_name)
    if val != "":
        return val

    # Try array access: if result_data is a list, try first element
    if isinstance(result_data, list) and result_data:
        val = _deep_get(result_data[0], field_name)
        if val != "":
            return val
        # Try on the "results" wrapper if present
        if isinstance(result_data[0], dict) and "results" in result_data[0]:
            val = _deep_get(result_data[0]["results"], field_name)
            if val != "":
                return val

    # Try alias from settings
    if field_name in aliases:
        alias = aliases[field_name]
        if alias:
            val = _deep_get(result_data, alias)
            if val != "":
                return val
            if isinstance(result_data, list) and result_data:
                val = _deep_get(result_data[0], alias)
                if val != "":
                    return val

    return val if val != "" else None


def _resolve_placeholders(
    inputs: dict[str, Any],
    results: dict[str, Any],
    ref_aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve ``${task_id.result.field}`` placeholders with actual values.

    Recursively walks the entire inputs tree (dicts, lists, strings) so
    placeholders nested inside structures are substituted, not just
    top-level string values. A placeholder may be the ENTIRE value or
    inline within a larger string (e.g. ``"https://x/${a.result.id}"``).

    If a task_id doesn't match a physical node ID, ``ref_aliases`` is
    checked to map symbolic refs (set by the Compiler) to task IDs.
    Unresolvable placeholders (dependency failed) become ``None`` so
    downstream tools never receive raw ``${...}`` strings.
    """
    # Fast-path: if no inputs contain placeholders, return inputs as-is
    if "${" not in str(inputs):
        return inputs
    return {
        k: _resolve_placeholder_value(v, results, ref_aliases)
        for k, v in inputs.items()
    }


def _resolve_placeholder_value(
    val: Any,
    results: dict[str, Any],
    ref_aliases: dict[str, str] | None,
) -> Any:
    """Recursively resolve placeholders within a single input value."""
    if isinstance(val, dict):
        return {
            k: _resolve_placeholder_value(v, results, ref_aliases)
            for k, v in val.items()
        }
    if isinstance(val, list):
        return [
            _resolve_placeholder_value(item, results, ref_aliases)
            for item in val
        ]
    if isinstance(val, str) and "${" in val:
        match = _PLACEHOLDER_RE.search(val)
        if match:
            resolved = _lookup_placeholder(match, results, ref_aliases)
            if match.group(0) == val:
                # Whole-string placeholder → typed value (or None on failure)
                return resolved
            # Inline placeholder → string substitution; keep the raw
            # placeholder if the dependency failed (do not fabricate data).
            if resolved is None:
                return val
            return val.replace(match.group(0), _stringify(resolved))
    return val


def _stringify(value: Any) -> str:
    """Render a resolved value for inline string substitution."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return str(value)
    return str(value)


def _is_permanent_http_error(result: Any) -> bool:
    """True when a tool result is a permanent (non-retryable) HTTP failure.

    Client errors (4xx) reflect invalid input, missing resources, or
    authorization problems — re-invoking the same endpoint will not fix
    them. Server errors (5xx) and timeouts remain retryable.

    Args:
        result: A ``ToolExecutionResult``/``ToolResult`` with ``status``
            and ``http_status`` attributes.

    Returns:
        True for permanent failures (4xx / validation), False otherwise.
    """
    status = getattr(result, "status", "") or ""
    if status in ("validation_error", "validation_failed"):
        return True
    http = getattr(result, "http_status", None)
    try:
        code = int(http) if http is not None else None
    except (TypeError, ValueError):
        code = None
    if code is None:
        return False
    # 4xx = permanent, except the transient 408 (timeout), 425 (too early)
    # and 429 (rate limit — retried with backoff).
    return _HTTP_4XX_MIN <= code < _HTTP_5XX_MIN and code not in (408, 425, 429)


_HTTP_4XX_MIN = 400
_HTTP_5XX_MIN = 500


def _lookup_placeholder(
    match: re.Match,
    results: dict[str, Any],
    ref_aliases: dict[str, str] | None,
) -> Any:
    """Resolve a single placeholder match to its value (or None)."""
    task_id = match.group(1)
    result_data = results.get(task_id)
    # Fall back to ref_alias lookup if task_id is a symbolic ref
    if result_data is None and ref_aliases:
        physical_id = ref_aliases.get(task_id)
        if physical_id:
            # Multi-item alias: comma-joined fan-out task ids —
            # aggregate each item's result into a list.
            if "," in physical_id:
                aggregated: list[Any] = []
                for item_id in physical_id.split(","):
                    if item_id in results:
                        aggregated.append(results[item_id])
                if aggregated:
                    result_data = aggregated
            else:
                result_data = results.get(physical_id)
    if result_data is None:
        # Dependency task failed — can't resolve this placeholder
        return None
    # Build path: optional [index] + optional .field
    idx_str = match.group(2)  # e.g. "0" or None
    field_path = match.group(3)  # e.g. "longitude" or None
    if idx_str is not None:
        path = f"[{idx_str}].{field_path}" if field_path else f"[{idx_str}]"
    else:
        path = field_path or ""
    if path:
        # Use _resolve_field which tries aliases if exact match fails
        val = _resolve_field(result_data, path)
        if val is None:
            # Try fallback: if result_data is wrapped in {"results": [...]}
            if isinstance(result_data, dict):
                inner = result_data.get("results") or result_data.get("data")
                if isinstance(inner, list) and inner:
                    val = _resolve_field(inner, path)
        return val
    return result_data


def _parse_path_segment(segment: str) -> tuple[str, int | None]:
    """Parse a path segment like ``results[0]`` into (key, index).

    Returns (key, None) for plain keys like ``latitude``.
    Returns (key, index) for indexed access like ``results[0]``.
    Returns ("", index) for pure index access like ``[0]``.
    """
    # Pure bracket-only index: [0]
    pure_idx = re.match(r"^\[(\d+)\]$", segment)
    if pure_idx:
        return "", int(pure_idx.group(1))
    # Key with index: results[0]
    match = re.match(r"^([^\[]+)\[(\d+)\]$", segment)
    if match:
        return match.group(1), int(match.group(2))
    return segment, None


def _deep_get(obj: Any, path: str) -> Any:
    """Resolve a dot-separated path into a nested dict/list structure.

    Handles:
    - Direct keys: ``latitude``
    - Indexed access: ``results[0].latitude`` (via bracket notation)
    - Nested chains: ``results[0].name``
    - Dynamic scan: if a key is not found directly, scans dict values
      for any list whose first element contains the key.
    """
    current = obj
    for segment in path.split("."):
        key, idx = _parse_path_segment(segment)

        # Pure index access: [N] — navigate into list
        if not key and idx is not None:
            if isinstance(current, list) and len(current) > idx:
                current = current[idx]
            elif isinstance(current, dict):
                # Scan dict values for a list
                for v in current.values():
                    if isinstance(v, list) and len(v) > idx:
                        current = v[idx]
                        break
                else:
                    return ""
            else:
                return ""
            continue

        if isinstance(current, dict):
            if key in current:
                current = current[key]
                if idx is not None and isinstance(current, list):
                    current = current[idx] if len(current) > idx else ""
            else:
                found = False
                for val in current.values():
                    if isinstance(val, dict) and key in val:
                        current = val[key]
                        found = True
                        break
                    if isinstance(val, list) and len(val) > 0:
                        target = val[idx] if idx is not None else val[0]
                        if isinstance(target, dict) and key in target:
                            current = target[key]
                            found = True
                            break
                        if idx is not None and idx < len(val):
                            current = val[idx]
                            found = True
                            break
                if not found:
                    return ""
        elif isinstance(current, list):
            target_idx = idx if idx is not None else 0
            if len(current) > target_idx:
                current = current[target_idx]
                if isinstance(current, dict) and key in current:
                    current = current[key]
                elif isinstance(current, dict):
                    current = current.get(key, "")
                else:
                    return ""
            else:
                return ""
        else:
            return ""
    return current


# ============================================================================
# Concurrent Executor
# ============================================================================


class ConcurrentExecutor:
    """Wave-based concurrent tool executor with fault isolation and retry.

    Features:
    - Per-domain adaptive concurrency: independent semaphores per API domain.
    - execution_key idempotency: tasks with the same (tool, inputs) hash
      are skipped if already completed in a prior retry iteration.
    - Ref-based placeholder resolution: placeholders like ${Geo.result.field}
      are resolved first by physical task ID, then by symbolic ref alias.

    Accepts ``ExecutionPlan`` from the DAG Planner and executes all tools
    through the configured ``ToolExecutor``.
    """

    def __init__(
        self,
        tool_executor: ToolExecutor | None = None,
        tool_map: dict[str, dict[str, Any]] | None = None,
        session_id: str = "",
        budget: Any = None,
        user_roles: list[str] | None = None,
    ) -> None:
        self._executor = tool_executor or ToolExecutor()
        self._settings = get_settings()
        self._tool_map: dict[str, dict[str, Any]] = tool_map or {}
        self._domain_semaphores: dict[str, asyncio.Semaphore] = {}
        self._completed_keys: set[str] = set()
        self._session_id = session_id
        self._ref_aliases: dict[str, str] = {}  # symbolic_ref → task_id
        self._conditional_branch: dict[str, list[str]] = {}
        self._disabled_task_ids: set[str] = set()
        # REASONING BUDGET (P0): the per-invocation tool-call budget —
        # every real tool execution reserves before the call; cache hits
        # do not consume (they are calls avoided).
        self._budget = budget
        self._user_roles = list(user_roles or [])
        from nexus.config.settings import get_settings as _ce_settings
        self._domain_cap = _ce_settings().tools.max_domain_concurrency

    def set_ref_aliases(self, aliases: dict[str, str]) -> None:
        """Register symbolic ref → task_id aliases for placeholder resolution.

        Allows placeholders like ${Geo.result.latitude} to resolve even
        though the physical task ID is a hash.
        """
        self._ref_aliases = dict(aliases)

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

        # Conditional-gate state: node id → enabled branch task ids. Tasks on
        # the inactive branch are skipped (recorded as skipped, not failed).
        self._conditional_branch: dict[str, list[str]] = {}

        try:
            async with asyncio.timeout(global_timeout):
                for wave in waves:
                    logger.info(
                        "concurrent_executor.wave_start",
                        wave=wave.wave,
                        task_count=len(wave.tasks),
                    )

                    # Evaluate conditional gates that are ready in THIS wave,
                    # then prune tasks whose branch is not selected.
                    executable = self._prune_conditional_tasks(
                        wave.tasks, task_map, accumulated,
                    )
                    if not executable:
                        logger.info(
                            "concurrent_executor.wave_pruned",
                            wave=wave.wave,
                        )
                        continue

                    wave_outcomes = await self._execute_wave(
                        wave=_WaveView(wave.wave, executable),
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
                        elif outcome.status == "skipped":
                            results.skipped.append(outcome.task_id)
                        else:
                            results.failed.append(outcome.task_id)

                    results.by_wave.append(wave_dict)

                    # Log errors for debugging (skip silent branch skips)
                    for outcome in wave_outcomes:
                        if outcome.status not in ("success", "skipped"):
                            logger.warning(
                                "concurrent_executor.task_failed",
                                task=outcome.task_id, tool=outcome.tool_name,
                                error=outcome.error,
                            )

                    logger.info(
                        "concurrent_executor.wave_done",
                        wave=wave.wave,
                        success=len(wave_outcomes) - sum(1 for o in wave_outcomes if o.status != "success"),
                        failed=len(results.failed),
                    )

        except asyncio.TimeoutError:
            logger.error("concurrent_executor.global_timeout", timeout=global_timeout)

        return results

    def _extract_domain(self, tool_name: str) -> str:
        """Extract the API domain for a tool.

        Reads ``endpoint_url`` from tool_map metadata, extracts hostname.
        Falls back to ``tool_name`` as the domain key if no URL is available.
        """
        tool_data = self._tool_map.get(tool_name, {})
        if isinstance(tool_data, dict):
            url = tool_data.get("endpoint_url") or tool_data.get("url", "")
            if url and isinstance(url, str):
                import re as _re

                m = _re.search(r"https?://([^/]+)", url)
                if m:
                    return m.group(1)
        return tool_name

    def _prune_conditional_tasks(
        self,
        wave_tasks: list[Any],
        task_map: dict[str, Any],
        accumulated: dict[str, Any],
    ) -> list[Any]:
        """Evaluate conditional gates in this wave and prune inactive branches.

        A conditional task carries ``kind == "conditional"`` plus
        ``condition``, ``branch_true`` and ``branch_false`` (node ids). When
        its dependencies are satisfied, the condition is evaluated against
        ``accumulated`` and the winning branch's task ids are recorded as
        enabled. Tasks belonging to the losing branch are dropped from the
        wave (they never execute — no side effects, no false failures).

        Returns the list of tasks that should actually run this wave.
        """
        from nexus.execution.condition_evaluator import evaluate_condition

        executable: list[Any] = []
        for task in wave_tasks:
            if getattr(task, "kind", "tool") != "conditional":
                executable.append(task)
                continue

            # Conditional gate: evaluate against accumulated results. If its
            # dependencies aren't satisfied yet (accumulated missing), the
            # gate stays inert — the branch is resolved on a later wave pass.
            try:
                taken = evaluate_condition(
                    task.condition or "",
                    accumulated,
                    self._ref_aliases,
                )
            except Exception as exc:
                logger.warning(
                    "concurrent_executor.condition_eval_failed",
                    task=task.id,
                    error=str(exc)[:200],
                )
                taken = False

            chosen = task.branch_true if taken else task.branch_false
            self._conditional_branch[task.id] = list(chosen)
            # Tasks on the LOSING branch are disabled — plus any task that
            # transitively depends on a disabled task (deterministic cascade).
            losing = [
                tid for tid in (task.branch_true + task.branch_false)
                if tid not in chosen
            ]
            self._disabled_task_ids.update(losing)
            logger.info(
                "concurrent_executor.conditional",
                task=task.id,
                taken=taken,
                branch_ids=chosen,
            )
            # The gate itself produces no result; branches run in later waves.
        return executable

    def _compute_execution_key(self, tool_name: str, inputs: dict) -> str:
        """Deterministic SHA256 hash of (tool_name, inputs) for idempotency."""
        payload = json.dumps({"tool_name": tool_name, "inputs": inputs}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def _sha256(self, payload: str) -> str:
        return hashlib.sha256(payload.encode()).hexdigest()

    async def _register_artifact(self, task: Any, result: ToolExecutionResult,
                                 tool_read: Any,
                                 exec_key: str | None = None) -> dict:
        """Normalize + register a successful tool result as an artifact.

        Shared by the fresh-execution and cache-hit paths so the ResponseNode
        always has the data (a cached hit must not leave an empty context).
        Normalization applies schema projection (the tool's declared top-level
        output fields) — metadata-driven.

        ARTIFACT STATE MACHINE (Step 1): RAW_TOOL_RESULT → normalize →
        NORMALIZED (marked) → strip marker → REGISTERED. The normalization
        state is carried BY THE PAYLOAD (the reserved ``_nx_state`` marker) —
        a normalized payload is self-describing and can never be normalized
        twice (``normalize_artifact`` raises on a marked payload).

        Args:
            task: The executed task.
            result: The successful tool result.
            tool_read: The tool metadata (schema source).
            exec_key: The INPUT-based execution key (idempotency key) — used
                for the normalized-artifact cache write so read/write keys
                match (a cache with mismatched keys is dead code).
        """
        from nexus.artifacts.base import ArtifactBase
        from nexus.artifacts.graph import get_artifact_graph
        from nexus.artifacts.normalizer import (
            ArtifactContractViolation,
            is_normalized,
            normalize_artifact,
            strip_normalization_state,
            validate_artifact_contract,
        )

        capability_id = getattr(task, "capability", task.tool_name)
        payload = result.data if isinstance(result.data, dict) else {}
        normalized_data: dict = {}
        try:
            from nexus.agent.architecture import ArchitectureVersion

            _arch_fp = ArchitectureVersion.cache_fingerprint()
            _out_schema = getattr(tool_read, "output_schema", None) or {}
            _allowed = None
            _flat: dict[str, str] | None = None
            _optional: set[str] | None = None
            if isinstance(_out_schema, dict):
                _props = _out_schema.get("properties")
                if isinstance(_props, dict) and _props:
                    _allowed = set(_props.keys())
                _flat_ext = _out_schema.get("x-artifact-fields")
                if isinstance(_flat_ext, dict) and _flat_ext:
                    _flat = {
                        str(k): str(v)
                        for k, v in _flat_ext.items()
                        if isinstance(k, str) and isinstance(v, str)
                    }
                _opt_ext = _out_schema.get("x-artifact-optional")
                if isinstance(_opt_ext, list) and _opt_ext:
                    _optional = {str(o) for o in _opt_ext if isinstance(o, str)}
            if is_normalized(payload):
                # ARTIFACT-CACHE reuse: the payload IS the normalized form.
                # Registration strips the state marker. Never re-normalized.
                normalized_data = payload
                logger.debug(
                    "concurrent_executor.artifact_reused_normalized",
                    task=task.id,
                    tool=tool_read.name,
                )
            else:
                normalized_data = normalize_artifact(
                    capability_id, payload,
                    allowed_fields=_allowed, flat_fields=_flat,
                )
            # CONTRACT VALIDATION (Step 2): every declared flat-field path must
            # resolve (or be declared optional). A violation ABORTS
            # registration — an all-None/empty artifact must never enter the
            # graph, and the failure is explicit, never silent.
            if _flat:
                try:
                    validate_artifact_contract(
                        capability_id, strip_normalization_state(normalized_data),
                        _flat, _optional, raw_data=payload,
                    )
                except ArtifactContractViolation as _violation:
                    logger.error(
                        "concurrent_executor.artifact_contract_violation",
                        task=task.id,
                        tool=tool_read.name,
                        error=str(_violation)[:300],
                    )
                    # Fall through WITHOUT registering: the raw data stays in
                    # tool_results; the response reports honestly.
                    return strip_normalization_state(normalized_data)
            # ARTIFACT CACHE (Phase 2/Step 3): persist the NORMALIZED (marked)
            # form keyed by the INPUT-based execution key — a later cache hit
            # reuses it and skips normalization entirely (synthesis never
            # re-normalizes; the marker makes the payload self-describing).
            try:
                from nexus.memory.store import MemoryStore

                await MemoryStore().put(
                    session_id=str(self._session_id) if self._session_id else None,
                    kind="normalized_artifact",
                    content=json.dumps(normalized_data, default=str),
                    metadata={
                        "execution_key": exec_key or self._compute_execution_key(
                            tool_read.name, payload
                        ),
                        "tool": tool_read.name,
                        "normalized": "true",
                        "arch_fp": _arch_fp,
                    },
                )
            except Exception as _art_cache_exc:
                logger.debug(
                    "concurrent_executor.artifact_cache_write_failed",
                    error=str(_art_cache_exc)[:150],
                )
        except Exception as _norm_exc:
            logger.warning(
                "concurrent_executor.normalize_failed",
                task=task.id,
                error=str(_norm_exc)[:200],
            )
        try:
            artifact_graph = get_artifact_graph(self._session_id)
            artifact = ArtifactBase(
                capability_id=capability_id,
                type=tool_read.category or "GenericArtifact",
                tool_name=tool_read.name,
                schema_version="1.0",
                artifact_revision=1,
                data=strip_normalization_state(normalized_data),
                execution_id=str(task.id),
            )
            artifact_graph.register(artifact)
            logger.debug(
                "concurrent_executor.artifact_registered",
                task=task.id,
                tool=tool_read.name,
                data_preview=str(dict(artifact.data))[:200],
                graph_count=len(artifact_graph.all()),
            )
            try:
                from nexus.artifacts.registry import ArtifactRegistry

                await ArtifactRegistry.register(
                    session_id=str(self._session_id) if self._session_id else None,
                    capability_id=capability_id,
                    tool_name=tool_read.name,
                    artifact_type=tool_read.category or "GenericArtifact",
                    schema_version="1.0",
                    artifact_revision=1,
                    data=normalized_data,
                    execution_id=str(task.id),
                )
            except Exception as _reg_db_exc:
                logger.warning(
                    "concurrent_executor.artifact_db_failed",
                    task=task.id,
                    error=str(_reg_db_exc)[:200],
                )
        except Exception as _reg_exc:
            logger.warning(
                "concurrent_executor.artifact_register_failed",
                task=task.id,
                error=str(_reg_exc)[:200],
            )
        # Return the STRIPPED normalized payload (no reserved markers) for
        # placeholder resolution and the tool-results channel.
        return strip_normalization_state(normalized_data)

    def _is_disabled(self, task: Any) -> bool:
        """True when a task sits on an inactive conditional branch.

        A task is disabled if it was directly listed on a losing branch, or
        if any of its dependencies were disabled (deterministic cascade).
        """
        if task.id in self._disabled_task_ids:
            return True
        deps = getattr(task, "depends_on", []) or []
        return any(d in self._disabled_task_ids for d in deps)

    async def _execute_wave(
        self,
        wave: Any,
        task_map: dict[str, Any],
        accumulated: dict[str, Any],
        max_concurrency: int,
        per_tool_timeout: float,
    ) -> list[ToolExecutionResult]:
        """Execute a single wave — run its tasks in parallel with per-domain concurrency cap.

        Each API domain gets its own semaphore (default cap=10) for independent
        rate limiting. Tasks with matching execution_keys are skipped (idempotency).
        Fault isolation: each task runs independently.
        """
        async def _run(task: Any) -> ToolExecutionResult:
            # Conditional branch pruning: tasks on a losing branch (or that
            # transitively depend on one) are SKIPPED — no execution, no
            # false failure. They simply contribute no result.
            if self._is_disabled(task):
                logger.info(
                    "concurrent_executor.branch_skipped",
                    task=task.id,
                    tool=task.tool_name,
                )
                return ToolExecutionResult(
                    task_id=task.id,
                    tool_name=task.tool_name,
                    status="skipped",
                )

            domain = self._extract_domain(task.tool_name)
            if domain not in self._domain_semaphores:
                self._domain_semaphores[domain] = asyncio.Semaphore(
                    self._domain_cap,
                )

            # Resolve placeholders BEFORE the idempotency check so the
            # execution key hashes the SAME (resolved) inputs that get
            # stored on success — raw-input keys could never match.
            resolved_inputs = _resolve_placeholders(task.inputs, accumulated, self._ref_aliases)
            exec_key = self._compute_execution_key(task.tool_name, resolved_inputs)
            if exec_key in self._completed_keys:
                logger.info("concurrent_executor.idempotent_skip", task=task.id, domain=domain)
                return ToolExecutionResult(
                    task_id=task.id,
                    tool_name=task.tool_name,
                    status="success",
                    data=accumulated.get(task.id),
                    execution_key=exec_key,
                )

            async with self._domain_semaphores[domain]:
                return await self._execute_single(
                    task=task,
                    task_map=task_map,
                    accumulated=accumulated,
                    timeout=per_tool_timeout,
                    pre_resolved_inputs=resolved_inputs,
                )

        outcomes = await asyncio.gather(
            *(_run(t) for t in wave.tasks),
            return_exceptions=True,
        )

        results: list[ToolExecutionResult] = []
        for i, outcome in enumerate(outcomes):
            task = wave.tasks[i]
            if isinstance(outcome, ToolExecutionResult):
                results.append(outcome)
            elif isinstance(outcome, Exception):
                results.append(ToolExecutionResult(
                    task_id=task.id,
                    tool_name=task.tool_name,
                    status="error",
                    error=str(outcome),
                ))
            else:
                results.append(ToolExecutionResult(
                    task_id=task.id,
                    tool_name=task.tool_name,
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
        pre_resolved_inputs: dict[str, Any] | None = None,
    ) -> ToolExecutionResult:
        """Execute a single tool task with retry policy, timeout, and endpoint fallback.

        Retry policy:
        - Retry up to ``task.max_retries`` times.
        - Exponential backoff: 2^attempt seconds between retries.
        - Only retry on transient errors (timeout, connection error, 5xx).
        - Do NOT retry validation errors or 4xx responses.

        Late-binding fallback:
        - If a task has ``candidate_endpoints`` (set by the Compiler/optimizer pass),
          a ``validation_error`` or ``error`` status will try the next candidate
          endpoint before failing.
        """
        import time as _time

        # Pre-resolved inputs (from the idempotency check) avoid resolving
        # twice; re-resolve when the caller skipped the check.
        resolved_inputs = (
            pre_resolved_inputs
            if pre_resolved_inputs is not None
            else _resolve_placeholders(task.inputs, accumulated, self._ref_aliases)
        )
        last_error: str | None = None

        # Prepare candidate list for late-binding fallback
        candidate_pool: list[dict] = list(getattr(task, "candidate_endpoints", []))
        current_url: str = getattr(task, "endpoint_url", "")
        current_method: str = getattr(task, "http_method", "GET")
        fallback_index: int = 0  # 0 = use current endpoint; 1+ = use candidates

        # Retry budget is metadata-driven: a non-idempotent tool must never be
        # retried after a transient failure — the first attempt may have
        # already fired the side effect. Defaults to non-idempotent (safe).
        _tool_meta = self._tool_map.get(task.tool_name)
        task_idempotent = bool(
            _tool_meta.get("idempotent", False) if isinstance(_tool_meta, dict) else False
        )
        task_retries = task.max_retries if task_idempotent else 0

        for attempt in range(task_retries + 1):
            try:
                # On fallback, pick a candidate endpoint
                if fallback_index > 0 and candidate_pool:
                    for cand in candidate_pool:
                        cand_url = cand.get("url", "")
                        if cand_url and cand_url != current_url:
                            current_url = cand_url
                            current_method = cand.get("http_method", current_method)
                            logger.info(
                                "concurrent_executor.fallback",
                                task=task.id,
                                candidate_url=current_url,
                                fallback_index=fallback_index,
                            )
                            break

                start = _time.perf_counter()

                from nexus.tools.schemas import ToolRead

                # Tool metadata is bound ONCE per attempt — safe default for
                # tools absent from the DB tool_map (e.g. compiled-graph-only
                # capabilities) so downstream reads never raise.
                tool_data = self._tool_map.get(task.tool_name, {})
                if not isinstance(tool_data, dict):
                    tool_data = {}

                if current_url:
                    from datetime import datetime, timezone
                    _now = datetime.now(timezone.utc).isoformat()
                    auth_type = tool_data.get("auth_type", "none")
                    auth_ref = tool_data.get("auth_ref", "")
                    # Fallback: resolve auth from GlobalContext capability_providers
                    if auth_type == "none" and not auth_ref:
                        from nexus.context.global_context import get_global_context
                        _gc = get_global_context()
                        _provs = _gc.capability_providers.get(task.tool_name, [])
                        if _provs:
                            auth_type = _provs[0].get("auth_type", "none")
                            auth_ref = _provs[0].get("auth_ref", "")
                    tool_read = ToolRead(
                        id=tool_data.get("id") or "00000000-0000-0000-0000-000000000000",
                        name=task.tool_name,
                        description=tool_data.get("description", ""),
                        purpose=tool_data.get("purpose", ""),
                        tool_type="http_api",
                        endpoint_url=current_url,
                        http_method=current_method,
                        auth_type=auth_type,
                        auth_ref=auth_ref,
                        input_schema=tool_data.get("input_schema", {}),
                        output_schema=tool_data.get("output_schema", {}),
                        validation_rules=tool_data.get("validation_rules", {}),
                        examples=tool_data.get("examples", []),
                        tags=tool_data.get("tags", []),
                        category=tool_data.get("category", "general"),
                        requires_approval=bool(tool_data.get("requires_approval", False)),
                        risk_level=tool_data.get("risk_level", "low"),
                        idempotent=bool(tool_data.get("idempotent", False)),
                        enabled=bool(tool_data.get("enabled", True)),
                        version=1,
                        created_at=_now,
                        updated_at=_now,
                    )
                else:
                    tool_read = self._tool_dict_to_read(task.tool_name)
                    if tool_read is None:
                        return ToolExecutionResult(
                            task_id=task.id,
                            tool_name=task.tool_name,
                            status="tool_not_found",
                            error=f"Tool '{task.tool_name}' not found in tool map",
                        )

                # Cacheable artifact read (Phase 5): a cacheable op reuses a
                # prior long-term result keyed by its execution key — the
                # external API is never called twice for the same input.
                _exec_key = self._compute_execution_key(task.tool_name, resolved_inputs)
                _tool_cacheable = bool(
                    tool_data.get("cacheable", True) if isinstance(tool_data, dict) else True
                )
                if _tool_cacheable and _exec_key not in self._completed_keys:
                    try:
                        from nexus.agent.architecture import ArchitectureVersion
                        from nexus.memory.store import MemoryStore

                        _hit = await MemoryStore().find_by_metadata(
                            {
                                "execution_key": _exec_key,
                                "tool": task.tool_name,
                                "arch_fp": ArchitectureVersion.cache_fingerprint(),
                            },
                            kind="artifact",
                            top_k=1,
                        )
                    except Exception as _mem_exc:
                        logger.warning(
                            "concurrent_executor.cache_read_failed",
                            task=task.id,
                            error=str(_mem_exc)[:200],
                        )
                        _hit = []
                    if _hit and isinstance(_hit[0].get("content"), str):
                        import json as _json

                        try:
                            _hit_data = _json.loads(_hit[0]["content"])
                        except Exception:
                            _hit_data = None
                        if isinstance(_hit_data, dict):
                            logger.info(
                                "concurrent_executor.cache_hit",
                                task=task.id,
                                tool=task.tool_name,
                            )
                            self._completed_keys.add(_exec_key)
                            # ARTIFACT CACHE reuse (Phase 2): a normalized
                            # artifact cached under the same execution key
                            # skips re-normalization (synthesis reads the
                            # normalized form directly).
                            _normalized: dict | None = None
                            try:
                                from nexus.agent.architecture import ArchitectureVersion
                                from nexus.artifacts.normalizer import NORMALIZER_VERSION
                                from nexus.memory.store import MemoryStore

                                _norm_hits = await MemoryStore().find_by_metadata(
                                    {
                                        "execution_key": _exec_key,
                                        "tool": task.tool_name,
                                        "normalized": "true",
                                        "arch_fp": ArchitectureVersion.cache_fingerprint(),
                                    },
                                    kind="normalized_artifact",
                                    top_k=1,
                                )
                                if _norm_hits and isinstance(
                                    _norm_hits[0].get("content"), str
                                ):
                                    _parsed = _json.loads(_norm_hits[0]["content"])
                                    # VERSIONED CACHE READ (ADR 0005): the
                                    # normalized payload carries the normalizer
                                    # version in its state marker — payloads
                                    # from older normalizers are stale by
                                    # contract (pre-fix runs persisted all-None
                                    # flattened payloads) and must NOT be
                                    # reused; the fresh path re-normalizes.
                                    if isinstance(_parsed, dict) and (
                                        _parsed.get("_nx_normalizer_version")
                                        == NORMALIZER_VERSION
                                    ):
                                        _normalized = _parsed
                            except Exception as _norm_cache_exc:
                                logger.debug(
                                    "concurrent_executor.artifact_cache_read_failed",
                                    error=str(_norm_cache_exc)[:150],
                                )
                            # Cache hits must register their artifact too —
                            # otherwise the ResponseNode never sees the data
                            # and composes from an empty context (honest but
                            # wrong: real data existed).
                            _cached_result = ToolExecutionResult(
                                task_id=task.id,
                                tool_name=task.tool_name,
                                status="success",
                                data=_hit_data,
                                duration_ms=0,
                                execution_key=_exec_key,
                                cached=True,
                            )
                            if _normalized is not None:
                                _cached_result.data = _normalized
                            await self._register_artifact(
                                task, _cached_result, tool_read,
                                exec_key=_exec_key,
                            )
                            # Never hand the reserved normalization markers
                            # downstream (events/placeholder resolution).
                            from nexus.artifacts.normalizer import (
                                strip_normalization_state as _strip_nx,
                            )
                            _cached_result.data = _strip_nx(
                                _cached_result.data or {}
                            )
                            return _cached_result

                # REASONING BUDGET (P0): reserve the tool-call budget BEFORE
                # the real HTTP/API execution (cache hits consumed nothing —
                # they are calls avoided). Exhausted → the typed failure
                # surfaces honestly; the recovery/response layers handle it.
                if self._budget is not None and not self._budget.consume("tool_calls"):
                    logger.error(
                        "concurrent_executor.tool_budget_exhausted",
                        task=task.id,
                        tool=task.tool_name,
                    )
                    return ToolExecutionResult(
                        task_id=task.id,
                        tool_name=task.tool_name,
                        status="error",

                        data=None,
                        error="invocation tool-call budget exhausted",
                        duration_ms=0,
                        execution_key=_exec_key,
                    )

                # IDEMPOTENCY (P0): the logical operation's idempotency key
                # is STABLE across retries and recovery attempts for the
                # same (tool, resolved inputs) — the provider-facing key the
                # ToolExecutor stamps on the request when the tool declares
                # an idempotency header. Attempt identity is tracked
                # separately (the retry index) — a retried call carries the
                # same key, so the provider can deduplicate.
                _op_id = f"{task.id}:{_exec_key}"
                _idem_key = self._sha256(f"{self._session_id}:{_op_id}")[:40]
                _attempt = attempt + 1
                _exec_ctx = ExecutionContext(
                    session_id=self._session_id,
                    agent_run_id=None,
                )
                _exec_ctx.idempotency_key = _idem_key
                _exec_ctx.user_roles = self._user_roles
                from nexus.db import async_session as db_session_factory
                async with db_session_factory() as db_session:
                    try:
                        result = await asyncio.wait_for(
                            self._executor.execute(
                                tool=tool_read,
                                inputs=resolved_inputs,
                                context=_exec_ctx,
                                session=db_session,
                                skip_approval=True,
                            ),
                            timeout=timeout,
                        )
                    except asyncio.CancelledError:
                        # CANCELLATION (P0): the invocation was cancelled
                        # DURING the call — the provider may have accepted
                        # the side effect. Mark the outcome UNCERTAIN (never
                        # retried, never reported as a plain failure).
                        logger.error(
                            "concurrent_executor.cancelled_mid_call",
                            task=task.id,
                            tool=task.tool_name,
                        )
                        return ToolExecutionResult(
                            task_id=task.id,
                            tool_name=task.tool_name,
                            status="uncertain",
                            data=None,
                            error="cancelled during execution — outcome uncertain",
                            duration_ms=0,
                            execution_key=_exec_key,
                        )

                duration = (_time.perf_counter() - start) * 1000

                if result.status == "success":
                    # Cache write-back (Phase 5): cacheable results persist to
                    # long-term memory keyed by execution key — the next run
                    # with identical inputs reuses this instead of the API.
                    if _tool_cacheable:
                        try:
                            import json as _json

                            from nexus.agent.architecture import ArchitectureVersion
                            from nexus.memory.store import MemoryStore

                            _payload = result.data
                            if isinstance(_payload, dict):
                                await MemoryStore().put(
                                    session_id=str(self._session_id) if self._session_id else None,
                                    kind="artifact",
                                    content=_json.dumps(_payload),
                                    metadata={
                                        "execution_key": _exec_key,
                                        "tool": task.tool_name,
                                        "cacheable": "true",
                                        "arch_fp": ArchitectureVersion.cache_fingerprint(),
                                    },
                                )
                        except Exception as _cache_exc:
                            logger.warning(
                                "concurrent_executor.cache_write_failed",
                                task=task.id,
                                error=str(_cache_exc)[:200],
                            )
                    # 2. Normalize payload (applies recursive _limit_payload as safety net).
                    # Schema projection first: only the tool's declared top-level
                    # output fields flow into the artifact (metadata-driven —
                    # prevents context overflow WITHOUT masking nested values).
                    # NOTE: normalization/registration failures must NOT retry
                    # the HTTP call — the side effect already happened. Catch
                    # here and return success with the raw data instead.
                    exec_key = self._compute_execution_key(task.tool_name, resolved_inputs)
                    self._completed_keys.add(exec_key)
                    normalized_data = await self._register_artifact(
                        task, result, tool_read,
                        exec_key=exec_key,
                    )
                    return ToolExecutionResult(
                        task_id=task.id,
                        tool_name=task.tool_name,
                        status="success",
                        data=normalized_data,  # Return normalized data for placeholder resolution
                        duration_ms=duration,
                        execution_key=exec_key,
                        attempt_id=_attempt,
                        idempotency_key=_idem_key,
                    )

                # Check if we should fallback to a candidate endpoint
                is_validation_error = result.status == "validation_error"
                is_contract_error = result.error and "contract" in str(result.error).lower()
                can_fallback = (
                    fallback_index < len(candidate_pool)
                    and candidate_pool
                    and (is_validation_error or is_contract_error)
                )
                if can_fallback:
                    fallback_index += 1
                    last_error = result.error or "Validation failed"
                    logger.warning(
                        "concurrent_executor.fallback_attempt",
                        task=task.id,
                        fallback_index=fallback_index,
                        remaining=len(candidate_pool) - fallback_index,
                    )
                    continue  # retry with next candidate (no backoff)

                # PERMANENT failures: input-schema rejection and 4xx client
                # errors will NEVER succeed by re-invoking the same endpoint —
                # do not retry them (contradicts the class docstring's "no
                # retry on 4xx" contract and wastes rate-limit quota).
                if is_validation_error or _is_permanent_http_error(result):
                    last_error = result.error or result.status
                    logger.warning(
                        "concurrent_executor.no_retry_permanent",
                        task=task.id,
                        status=result.status,
                        error=str(last_error)[:200],
                    )
                    return ToolExecutionResult(
                        task_id=task.id,
                        tool_name=task.tool_name,
                        status=result.status,
                        error=last_error,
                    )

                # Normal retry for transient errors
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


    def _tool_dict_to_read(self, tool_name: str) -> Any:
        """Look up tool metadata — first from tool_map, then fallback to stub."""
        from nexus.tools.schemas import ToolRead

        tool_data = self._tool_map.get(tool_name)
        if tool_data:
            try:
                return ToolRead.model_validate(tool_data)
            except Exception as exc:
                logger.warning("concurrent_executor.tool_validate_failed",
                               tool=tool_name, error=str(exc))
                # fall through to stub

        # Fallback stub — the tool is not in the DB tool_map (compiled-graph
        # capabilities): resolve the endpoint from the GlobalContext provider
        # universe (metadata-driven — the provider rows ARE the contract).
        # Only when NO provider URL exists does execution fail explicitly.
        endpoint_url = ""
        http_method = "GET"
        auth_type = "none"
        auth_ref = ""
        input_schema: dict = {}
        output_schema: dict = {}
        try:
            from nexus.context.global_context import get_global_context

            _gc = get_global_context()
            _provs = (_gc.capability_providers or {}).get(tool_name, [])
            for _p in _provs:
                if isinstance(_p, dict) and _p.get("url"):
                    endpoint_url = str(_p["url"])
                    http_method = str(_p.get("http_method") or "GET")
                    auth_type = str(_p.get("auth_type") or "none")
                    auth_ref = str(_p.get("auth_ref") or "")
                    break
        except Exception:
            pass

        # Fallback stub — will cause an execution error downstream
        uuid_val = "00000000-0000-0000-0000-000000000000"
        from datetime import datetime, timezone
        now_str = datetime.now(timezone.utc).isoformat()
        return ToolRead(
            id=uuid_val,
            name=tool_name,
            description="",
            purpose="",
            tool_type="http_api",
            endpoint_url=endpoint_url,
            http_method=http_method,
            auth_type=auth_type,
            auth_ref=auth_ref,
            input_schema=input_schema,
            output_schema=output_schema,
            validation_rules={},
            examples=[],
            tags=[],
            category="general",
            requires_approval=False,
            risk_level="low",
            enabled=True,
            version=1,
            created_at=now_str,
            updated_at=now_str,
        )


# Import for type hint
from nexus.tools.executor import ExecutionContext  # noqa: E402, F811
