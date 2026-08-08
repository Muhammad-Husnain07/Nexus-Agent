"""
Dynamic DAG Planner — constructs a Directed Acyclic Graph of tool tasks.

This is now a thin shim. The heavy lifting has moved to:
- ``compiler/codegen.py`` — deterministic Compiler that resolves logical
  operations to physical endpoints and builds the ExecutionGraph.
- The LLM is called to produce a ``LogicalWorkflow``, which the Compiler
  then translates into an ``ExecutionGraph``.

Backward-compat data classes ``ExecutionTask``, ``ExecutionWave``, and
``ExecutionPlan`` are preserved for the ExecutorNode.

No hardcoded tool names. No deterministic planning heuristics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import structlog

from nexus.agent.planners.dependency_analysis import analyze_dependencies as _analyze_dependencies
from nexus.compiler.codegen import Compiler
from nexus.compiler.ir_models import LogicalNode, LogicalWorkflow, ToolNode, MapNode
from nexus.config.settings import get_settings

logger = structlog.get_logger("nexus.agent.planners.dag_planner")


# ============================================================================
# Exceptions
# ============================================================================


class PlanningError(Exception):
    """Raised when the DAG planner encounters an unrecoverable error."""
    pass


# ============================================================================
# Data Classes (preserved for ExecutorNode backward compat)
# ============================================================================


@dataclass
class ExecutionTask:
    """A single task in the execution plan."""
    id: str
    tool_name: str
    description: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    max_retries: int = 2
    timeout_s: float = 15.0
    endpoint_url: str = ""  # Resolved by Compiler — executor reads this directly
    http_method: str = "GET"  # Resolved by Compiler — executor reads this directly
    candidate_endpoints: list[dict[str, Any]] = field(default_factory=list)
    # Conditional gate metadata (kind == "conditional"): the executor evaluates
    # ``condition`` against accumulated results and enables exactly one branch.
    kind: str = "tool"  # tool | map | conditional
    condition: str = ""
    branch_true: list[str] = field(default_factory=list)
    branch_false: list[str] = field(default_factory=list)


@dataclass
class ExecutionWave:
    """A set of tasks that can execute in parallel (no dependencies between them)."""
    wave: int
    tasks: list[ExecutionTask]


@dataclass
class ExecutionPlan:
    """Complete execution plan with typed waves and metadata."""
    waves: list[ExecutionWave]
    tool_names: list[str]
    dependencies: list[tuple[str, str]]
    root_nodes: list[str]
    leaf_nodes: list[str]


# ============================================================================
# Public API
# ============================================================================


class PlannerRunner:
    """Backward-compat shim wrapping the updated build_plan function."""

    @staticmethod
    async def build_plan(
        intents: list[str] | None = None,
        tools: list[dict[str, Any]] | None = None,
        user_input: str = "",
        llm: Any = None,
        model: str | None = None,
        capabilities_context: str = "",
        state: dict[str, Any] | None = None,
    ) -> ExecutionPlan:
        return await build_plan(
            intents=intents,
            tools=tools,
            user_input=user_input,
            llm=llm,
            model=model,
            capabilities_context=capabilities_context,
            state=state,
        )


async def build_plan(
    intents: list[str] | None = None,
    tools: list[dict[str, Any]] | None = None,
    user_input: str = "",
    llm: Any = None,
    model: str | None = None,
    capabilities_context: str = "",
    state: dict[str, Any] | None = None,
    db_session: Any = None,
) -> ExecutionPlan:
    """Build an execution plan from user input + available tools.

    Calls the LLM to produce a ``LogicalWorkflow``, then feeds it to the
    deterministic ``Compiler`` to produce an ``ExecutionGraph``, which is
    then converted to the backward-compatible ``ExecutionPlan`` format.

    Args:
        intents: Parsed intents from the router (informational only).
        tools: Available tool metadata (state["available_tools"]).
        user_input: Raw user message.
        llm: LLM client for workflow generation.
        model: Model name.
        capabilities_context: Optional capability registry context.
        state: Current AgentState.
        db_session: Async DB session for the Compiler.

    Returns:
        An ``ExecutionPlan`` with waves, dependencies, and metadata.

    Raises:
        PlanningError: If the Compiler detects cycles.
    """
    tools = tools or []
    user_input = user_input or ""

    # Call LLM to produce a LogicalWorkflow
    logical_workflow = await _call_llm_for_workflow(
        user_input=user_input,
        tools=tools,
        llm=llm,
        model=model,
        capabilities_context=capabilities_context,
    )

    # Feed to the deterministic Compiler (Compiler expects a resolver, not a
    # raw session — wrap the session in the production resolver)
    from nexus.capabilities.resolver import DynamicCapabilityResolver

    if db_session is None:
        from nexus.db.base import async_session as _session_factory
        async with _session_factory() as session:
            compiler = Compiler(DynamicCapabilityResolver(session))
            graph = await compiler.compile(logical_workflow)
    else:
        compiler = Compiler(DynamicCapabilityResolver(db_session))
        graph = await compiler.compile(logical_workflow)

    # Convert ExecutionGraph → ExecutionPlan (backward compat)
    return _graph_to_plan(graph)


async def _call_llm_for_workflow(
    user_input: str,
    tools: list[dict[str, Any]],
    llm: Any,
    model: str | None,
    capabilities_context: str = "",
) -> LogicalWorkflow:
    """Call the LLM to produce a LogicalWorkflow from the user's request.

    Falls back to a single-node LogicalWorkflow if the LLM is unavailable
    or the workflow can't be parsed.
    """
    from nexus.agent.prompts import prompt_manager

    capabilities = [t.get("name", "?") for t in tools[:30]]
    query = user_input[:1000]
    if capabilities_context:
        query = f"{capabilities_context}\n\nUser: {query}"

    try:
        prompt = prompt_manager.render(
            "logical_planner", "1.0",
            capabilities=", ".join(capabilities) if capabilities else "(none available)",
        )
    except Exception:
        prompt = f"User request: {query}"

    if llm is None or model is None:
        return LogicalWorkflow(
            nodes=[LogicalNode(op="unknown", ref="Fallback", inputs={})],
        )

    try:
        response = await llm.complete(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": query},
            ],
            temperature=0,
            max_tokens=get_settings().agent.planner_max_tokens,
            response_format={"type": "json_object"},
        )
        content = response.content or "{}"
        parsed = json.loads(content)

        nodes_data = parsed.get("nodes", parsed.get("tasks", []))
        if not nodes_data:
            return LogicalWorkflow(
                nodes=[LogicalNode(op="unknown", ref="Fallback", inputs={})],
            )

        nodes = []
        for i, nd in enumerate(nodes_data):
            if isinstance(nd, dict):
                nodes.append(LogicalNode(
                    op=nd.get("op", nd.get("tool_name", f"tool_{i}")),
                    ref=nd.get("ref", nd.get("description", f"ref_{i}")),
                    inputs=nd.get("inputs", {}),
                    depends_on=nd.get("depends_on", []),
                    condition=nd.get("condition"),
                    iterate_over=nd.get("iterate_over"),
                ))
        return LogicalWorkflow(nodes=nodes)
    except Exception:
        return LogicalWorkflow(
            nodes=[LogicalNode(op="unknown", ref="Fallback", inputs={})],
        )


def _graph_to_plan(graph: Any) -> ExecutionPlan:
    """Convert an ExecutionGraph to the backward-compatible ExecutionPlan format.

    Maps PhysicalNodes (ToolNode, MapNode) to ExecutionTasks, builds waves,
    and computes root/leaf nodes.
    """
    tasks: list[ExecutionTask] = []
    all_deps: list[tuple[str, str]] = []

    for nid, node in graph.nodes.items():
        if isinstance(node, ToolNode):
            task = ExecutionTask(
                id=nid,
                tool_name=node.tool_name,
                description=node.symbolic_ref,
                inputs=dict(node.inputs),
                depends_on=list(node.depends_on),
            )
            tasks.append(task)
            for dep in node.depends_on:
                all_deps.append((dep, nid))
        elif isinstance(node, MapNode):
            task = ExecutionTask(
                id=nid,
                tool_name=node.body.tool_name if node.body else "map",
                description=f"map over {node.iterate_over}",
                inputs=dict(node.body.inputs) if node.body else {},
                depends_on=list(node.depends_on),
            )
            tasks.append(task)
            for dep in node.depends_on:
                all_deps.append((dep, nid))

    # Build waves from ExecutionGraph's pre-computed waves
    waves: list[ExecutionWave] = []
    task_map = {t.id: t for t in tasks}
    for i, wave_ids in enumerate(graph.waves or []):
        wave_tasks = [task_map[w] for w in wave_ids if w in task_map]
        wave_tasks.sort(key=lambda t: t.id)
        waves.append(ExecutionWave(wave=i, tasks=wave_tasks))

    # If no pre-computed waves, build from dependencies
    if not waves:
        dag: dict[str, set[str]] = {t.id: set() for t in tasks}
        for dep, child in all_deps:
            dag.setdefault(dep, set()).add(child)
        in_degree = {n: 0 for n in dag}
        for node, children in dag.items():
            for child in children:
                in_degree[child] = in_degree.get(child, 0) + 1
        queue = [n for n, d in in_degree.items() if d == 0]
        wave_idx = 0
        while queue:
            wave_tasks = [task_map[q] for q in queue if q in task_map]
            wave_tasks.sort(key=lambda t: t.id)
            waves.append(ExecutionWave(wave=wave_idx, tasks=wave_tasks))
            next_queue = []
            for node in queue:
                for child in dag.get(node, set()):
                    in_degree[child] -= 1
                    if in_degree[child] == 0:
                        next_queue.append(child)
            queue = next_queue
            wave_idx += 1

    tool_names = list({t.tool_name for t in tasks})
    root_nodes = [t.id for t in tasks if not t.depends_on]
    leaf_nodes = [t.id for t in tasks if t.id not in dag or not dag[t.id]]

    return ExecutionPlan(
        waves=waves,
        tool_names=tool_names,
        dependencies=all_deps,
        root_nodes=root_nodes,
        leaf_nodes=leaf_nodes,
    )
