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

PLANNER_PROMPT = """You are a task planner. Given the user request and a list of available tools, determine which tools to use and how to pass data between them.

Available tools:
{tool_descriptions}

User request: {query}

Rules:
1. Select the tools needed to fulfill the request.
2. Identify data dependencies between tools. If Tool A produces data that Tool B needs as input, Tool A must run BEFORE Tool B.
3. Common dependency chains:
   - get_geocoding outputs latitude/longitude → get_weather needs latitude/longitude
   - get_geocoding outputs latitude/longitude → get_air_quality needs latitude/longitude
4. If a tool needs coordinates but the user only provided a city name, include get_geocoding as a prerequisite.
5. If a task has no data dependencies, it can run in parallel with other independent tasks.
6. **IMPORTANT: Include ALL relevant optional parameters.** For weather queries, always set ``current_weather`` to ``true`` so the API returns actual temperature and conditions. If you are unsure whether a parameter is needed, include it.

Return JSON:
```json
{{
  "tasks": [
    {{
      "id": "task_1",
      "tool_name": "get_geocoding",
      "inputs": {{"name": "Islamabad"}},
      "description": "Geocode city name to coordinates"
    }},
    {{
      "id": "task_2",
      "tool_name": "get_weather",
      "inputs": {{"latitude": "${{task_1.result.latitude}}", "longitude": "${{task_1.result.longitude}}", "current_weather": true}},
      "depends_on": ["task_1"],
      "description": "Get current temperature and weather conditions for coordinates"
    }}
  ]
}}
```

Only include tools from the available list. Use ${{task_X.result.field}} syntax for data dependencies."""


# ============================================================================
# Dependency Analyzer
# ============================================================================


def _inject_implicit_deps(
    tools: list[dict[str, Any]],
    user_input: str,
) -> list[dict[str, Any]]:
    """Detect implicit dependencies and inject prerequisite tools.

    For example, if the user asks for weather in "Lahore" and no geocoding
    tool is in the list, insert ``get_geocoding`` automatically since
    ``get_weather`` needs coordinates.
    """
    tool_names = {t["name"] for t in tools}
    modified = list(tools)

    # If get_weather is requested and get_geocoding is available but missing
    if "get_weather" in tool_names and "get_geocoding" not in tool_names:
        # Check if the user mentioned a city name (not coordinates)
        city_pattern = re.compile(
            r"(weather|temperature|forecast)\s+(in|of|for|at)\s+"
            r"([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)",
            re.IGNORECASE,
        )
        if city_pattern.search(user_input):
            logger.info("dag_planner.implicit_dep_inject", tool="get_geocoding")
            modified.insert(0, {
                "name": "get_geocoding",
                "description": "Geocode city name to coordinates",
                "input_schema": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string", "description": "City name to geocode"}
                    }
                },
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "latitude": {"type": "number"},
                        "longitude": {"type": "number"},
                    }
                },
            })

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
        required = t.get("input_schema", {}).get("required", [])
        outputs = list(t.get("output_schema", {}).get("properties", {}).keys())
        lines.append(
            f"- {name}: {desc} | inputs: {required} | outputs: {outputs}"
        )
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

    # 1. Inject implicit dependencies
    tools = _inject_implicit_deps(tools, user_input)

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
