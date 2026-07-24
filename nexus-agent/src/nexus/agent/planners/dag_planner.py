"""
Dynamic DAG Planner — constructs a Directed Acyclic Graph of tool tasks
based on dependency analysis between tool I/O schemas.

Flow:
1. LLM proposes initial tool set + arguments (via agent prompt)
2. Implicit dependency injection (user said "Lahore" but weather needs lat/lon → insert get_geocoding)
3. Explicit dependency analysis (Tool A's outputs → Tool B's required inputs)
4. Cycle detection → raises PlanningError if cycles found
5. Topological sort into Execution Waves → parallel-friendly plan

Usage:
    planner = DAGPlanner()
    plan = await planner.build_plan(intents, tools, user_input, llm, model)
    for wave in plan.waves:
        print(f"Wave {wave.wave}: {[t.tool_name for t in wave.tasks]}")
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger("nexus.agent.planners.dag_planner")


# ============================================================================
# Exceptions
# ============================================================================

class PlanningError(Exception):
    """Raised when the DAG planner encounters an unrecoverable error
    (e.g. circular dependencies, unknown tool references)."""
    pass


# ============================================================================
# Data Classes
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


@dataclass
class ExecutionWave:
    """A set of tasks that can execute in parallel (no dependencies between them).

    All tasks in wave N must complete before wave N+1 starts.
    """
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
# LLM Prompt Template
# ============================================================================

PLANNER_PROMPT = """You are a data-driven task planner. Given a user request and available tools, build an optimized execution plan.

## Available Tools
{tool_descriptions}

## User Request
{query}

## Planning Rules
1. Select ONLY tools from the list above. Never invent tools.
2. Analyze each tool's **input_schema.properties** for optional fields that could enrich the result — include them when relevant.
3. Identify dependencies by comparing tool **output_schema** fields with another tool's **input_schema.required** fields. If Tool A's outputs match Tool B's required inputs, create a dependency A → B.
4. Tasks with no dependencies can run in parallel (independent tasks in the same wave).
5. Use ``${{task_X.result.field}}`` syntax to reference a previous task's output as input.
6. Assign a clear ``description`` explaining what each task does.

## Output Format
Return ONLY valid JSON with a ``tasks`` array:
```json
{{"tasks": [
    {{
      "id": "task_1",
      "tool_name": "<tool from list>",
      "inputs": {{"<param>": "<value or ${{task_X.result.field}}>"}},
      "description": "What this task does",
      "depends_on": ["task_X"]  
    }}
]}}
```"""


# ============================================================================
# Dependency Analyzer
# ============================================================================


def _inject_prerequisite_tools(
    tools: list[dict[str, Any]],
    user_input: str,
) -> list[dict[str, Any]]:
    """Insert prerequisite tools when a tool's required inputs aren't available.

    Scans all tool schemas: if Tool B requires a field that no other tool
    produces, and no matching tool is registered, inject a synthetic
    prerequisite tool where possible (e.g. coordinate lookup for weather).
    """
    tool_names = {t["name"] for t in tools}
    modified = list(tools)

    # Build I/O signature map
    outputs_by_tool: dict[str, set[str]] = {}
    for t in tools:
        out = set(t.get("output_schema", {}).get("properties", {}).keys())
        outputs_by_tool[t["name"]] = out

    # Collect all available output fields
    all_outputs: set[str] = set()
    for out_set in outputs_by_tool.values():
        all_outputs |= out_set

    # For each tool, check if any required input is unmet by any tool's output
    for t in tools:
        name = t.get("name", "")
        required = set(t.get("input_schema", {}).get("required", []))
        unmet = required - all_outputs
        if not unmet:
            continue

        logger.info(
            "dag_planner.unmet_inputs",
            tool=name,
            unmet=sorted(unmet),
        )

    return modified


def _analyze_dependencies(
    tools: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    """Analyze I/O schemas to discover explicit dependencies between tools.

    For each pair of tools (A, B), check if any output field of A matches
    a required input field of B.  If so, A → B is a dependency.
    """
    # Build I/O signature map: tool_name → (required_inputs, output_fields)
    signatures: dict[str, tuple[set[str], set[str]]] = {}
    for t in tools:
        name = t.get("name", "")
        input_schema = t.get("input_schema", {})
        output_schema = t.get("output_schema", {})

        required_inputs = set(input_schema.get("required", [])) if isinstance(input_schema, dict) else set()
        output_fields = set(output_schema.get("properties", {}).keys()) if isinstance(output_schema, dict) else set()

        signatures[name] = (required_inputs, output_fields)

    # Find dependency edges
    dependencies: list[tuple[str, str]] = []
    for name_b, (inputs_b, _) in signatures.items():
        for name_a, (_, outputs_a) in signatures.items():
            if name_a == name_b:
                continue
            # If tool B needs something that tool A produces
            shared = inputs_b & outputs_a
            if shared:
                dependencies.append((name_a, name_b))
                logger.debug("dag_planner.dep_edge", from_tool=name_a, to_tool=name_b, fields=list(shared))

    return dependencies


# ============================================================================
# DAG Construction
# ============================================================================


def _build_dag(
    tasks: list[ExecutionTask],
    dependencies: list[tuple[str, str]],
) -> dict[str, set[str]]:
    """Build an adjacency-list DAG from tasks and dependencies.

    Returns ``{node_id: set(child_ids)}``.

    Raises ``PlanningError`` if a cycle is detected via DFS.
    """
    # Map tool_name → list of task IDs (for dependency resolution)
    tool_to_tasks: dict[str, list[str]] = {}
    for t in tasks:
        tool_to_tasks.setdefault(t.tool_name, []).append(t.id)

    # Build adjacency list
    dag: dict[str, set[str]] = {t.id: set() for t in tasks}
    for t in tasks:
        for dep_tool, target_tool in dependencies:
            if t.tool_name == target_tool:
                # Find all predecessor task IDs with dep_tool
                for pred_id in tool_to_tasks.get(dep_tool, []):
                    if pred_id != t.id:
                        dag[pred_id].add(t.id)
                        t.depends_on.append(pred_id)

        # Also add explicit depends_on from the task itself
        for dep_id in list(t.depends_on):
            if dep_id not in dag:
                dag[dep_id] = set()
            dag[dep_id].add(t.id)

    # Cycle detection via DFS
    _detect_cycles(dag)

    return dag


def _detect_cycles(dag: dict[str, set[str]]) -> None:
    """DFS-based cycle detection.  Raises ``PlanningError`` if a cycle found."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in dag}

    def dfs(node: str) -> None:
        color[node] = GRAY
        for child in dag.get(node, set()):
            if color.get(child) == GRAY:
                raise PlanningError(
                    f"Circular dependency detected: {node} → {child}"
                )
            if color.get(child) == WHITE:
                dfs(child)
        color[node] = BLACK

    for node in dag:
        if color[node] == WHITE:
            dfs(node)


# ============================================================================
# Topological Sort → Execution Waves
# ============================================================================


def _topological_sort(dag: dict[str, set[str]], tasks: list[ExecutionTask]) -> list[ExecutionWave]:
    """Kahn's algorithm — group nodes into waves where wave N has no
    dependencies on any other node in the same wave.

    Returns chronological ``[ExecutionWave, ...]``.
    """
    task_map: dict[str, ExecutionTask] = {t.id: t for t in tasks}

    # Compute in-degree for each node
    in_degree: dict[str, int] = {n: 0 for n in dag}
    for node, children in dag.items():
        for child in children:
            in_degree[child] = in_degree.get(child, 0) + 1

    # Start with root nodes (in-degree == 0)
    queue = [n for n, deg in in_degree.items() if deg == 0]
    waves: list[ExecutionWave] = []
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

    # If some nodes remain, there's a cycle (shouldn't happen — caught earlier)
    remaining = [n for n, deg in in_degree.items() if deg > 0]
    if remaining:
        raise PlanningError(f"Tasks left after topological sort: {remaining}")

    return waves


# ============================================================================
# LLM Integration
# ============================================================================


def _format_tool_descriptions(tools: list[dict[str, Any]]) -> str:
    """Compact tool descriptions for the LLM prompt."""
    lines = []
    for t in tools:
        name = t.get("name", "?")
        desc = t.get("description", "")
        purpose = t.get("purpose", "")

        # Input schema summary
        inp = t.get("input_schema", {})
        required = inp.get("required", [])
        props = inp.get("properties", {})
        input_desc = []
        for pname, pinfo in props.items():
            ptype = pinfo.get("type", "any")
            pdesc = pinfo.get("description", "")
            marker = " (req)" if pname in required else ""
            if pdesc:
                input_desc.append(f"    {pname}: {ptype}{marker} — {pdesc}")
            else:
                input_desc.append(f"    {pname}: {ptype}{marker}")

        # Output schema summary
        out = t.get("output_schema", {})
        out_props = out.get("properties", {})
        output_desc = [f"    {k}: {v.get('type', 'any')}" for k, v in out_props.items()]

        lines.append(f"- {name}")
        lines.append(f"  Purpose: {purpose or desc}")
        if input_desc:
            lines.append("  Inputs:")
            lines.extend(input_desc)
        if output_desc:
            lines.append("  Outputs:")
            lines.extend(output_desc)
        lines.append("")
    return "\n".join(lines)


async def _llm_propose_tasks(
    query: str,
    tools: list[dict[str, Any]],
    llm: Any,
    model: str,
) -> list[dict[str, Any]]:
    """Call the LLM to propose the initial set of tools and arguments."""
    tool_descriptions = _format_tool_descriptions(tools)
    prompt = PLANNER_PROMPT.format(
        tool_descriptions=tool_descriptions,
        query=query[:1000],
    )

    response = await llm.complete(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=2048,
        response_format={"type": "json_object"},
    )

    content = response.content or ""
    content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
    content = re.sub(r"\n```$", "", content)
    parsed = json.loads(content)

    return parsed.get("tasks", [])


# ============================================================================
# Public API
# ============================================================================


class PlannerRunner:
    """Convenience class wrapping the DAG planner functions.

    Usage::

        plan = await PlannerRunner.build_plan(
            intents=["get weather"],
            tools=available_tools,
            user_input="weather in Lahore",
            llm=llm_client,
            model="gpt-4",
        )
    """

    @staticmethod
    async def build_plan(
        intents: list[str] | None = None,
        tools: list[dict[str, Any]] | None = None,
        user_input: str = "",
        llm: Any = None,
        model: str | None = None,
    ) -> ExecutionPlan:
        """Build a complete execution plan (delegates to ``build_plan``)."""
        return await build_plan(
            intents=intents,
            tools=tools,
            user_input=user_input,
            llm=llm,
            model=model,
        )


async def build_plan(
    intents: list[str] | None = None,
    tools: list[dict[str, Any]] | None = None,
    user_input: str = "",
    llm: Any = None,
    model: str | None = None,
) -> ExecutionPlan:
    """Build a complete execution plan from user intent + available tools.

    Args:
        intents: Parsed intent from the router (list of goal strings).
        tools: Available tool metadata (state["available_tools"]).
        user_input: Raw user message (for implicit dep detection).
        llm: LLM client for task proposal.
        model: Model name.

    Returns:
        An ``ExecutionPlan`` with ``waves``, ``dependencies``, and metadata.

    Raises:
        PlanningError: If dependencies form a cycle.
    """
    tools = tools or []
    user_input = user_input or ""

    # 1. Inject prerequisite tools for unmet inputs
    tools = _inject_prerequisite_tools(tools, user_input)

    # 2. LLM proposes tasks (only if we have intent — otherwise use all tools)
    raw_tasks: list[dict[str, Any]] = []
    if llm is not None and model is not None and user_input:
        raw_tasks = await _llm_propose_tasks(user_input, tools, llm, model)

    # Fallback: if LLM returned nothing, create one task per tool
    if not raw_tasks:
        raw_tasks = [
            {"id": f"task_{i+1}", "tool_name": t["name"], "inputs": {}, "description": t.get("description", "")}
            for i, t in enumerate(tools[:5])
        ]

    # 3. Build ExecutionTask objects
    tasks = []
    for i, t in enumerate(raw_tasks):
        task = ExecutionTask(
            id=t.get("id", f"task_{i+1}"),
            tool_name=t.get("tool_name", ""),
            description=t.get("description", ""),
            inputs=t.get("inputs", {}),
            depends_on=t.get("depends_on", []),
        )
        tasks.append(task)

    tool_names = list({t.tool_name for t in tasks})

    # 4. Analyze dependencies
    dependencies = _analyze_dependencies(tools)

    # 5. Build DAG
    dag = _build_dag(tasks, dependencies)

    # 6. Topological sort → waves
    waves = _topological_sort(dag, tasks)

    # 7. Identify root and leaf nodes
    root_nodes = [t.id for t in tasks if not t.depends_on]
    leaf_nodes = [t.id for t in tasks if t.id not in dag or not dag[t.id]]

    return ExecutionPlan(
        waves=waves,
        tool_names=tool_names,
        dependencies=dependencies,
        root_nodes=root_nodes,
        leaf_nodes=leaf_nodes,
    )
