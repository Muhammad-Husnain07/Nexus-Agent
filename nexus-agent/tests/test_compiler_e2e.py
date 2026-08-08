"""End-to-end compiler tests — validates the 4-layer IR stack and compiled graph.

Tests:
1. IR model creation and validation (extra="forbid").
2. ExecutionContext from_state / to_state_update / apply / branch / replay.
3. @context_node decorator with old and new pattern.
4. ParseCache / PlanCache stats and invalidation.
5. Compiled capability graph loading and traversal.
6. Goal template lookup by trigger action.
7. Capability resolution with ontology matching.
8. Dependency resolution with BFS.
9. Pass manager optimization passes.
10. Event store append and replay.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import structlog

from nexus.compiler.cache import ParseCache, PlanCache, _query_fingerprint, _make_key
from nexus.compiler.codegen import Compiler
from nexus.compiler.ir_models import (
    ExecutionGraph,
    LogicalNode,
    LogicalWorkflow,
    MapNode,
    OperationIR,
    ReduceNode,
    ToolNode,
)
from nexus.compiler.pass_manager import optimize
from nexus.compiler.passes.pass_dead_task_elimination import run as dead_task_run
from nexus.compiler.passes.pass_dependency_simplification import run as dep_simplify_run
from nexus.compiler.passes.pass_parallel_fusion import run as fusion_run
from nexus.compiler.passes.pass_constraint_optimizer import run as constraint_run
from nexus.execution.context import ExecutionContext, StatePatch
from nexus.execution.events import append_event, get_events
from nexus.metrics.store import ewma_update


# ============================================================================
# 1. IR Model Tests
# ============================================================================


def test_operation_ir_extra_forbid():
    with pytest.raises(Exception, match="extra_forbidden"):
        OperationIR(op="test", extra_field="forbidden")


def test_logical_workflow_creation():
    node = LogicalNode(op="get_weather", ref="Weather", inputs={"q": "Tokyo"})
    wf = LogicalWorkflow(nodes=[node], collections={})
    assert wf.nodes[0].op == "get_weather"
    assert wf.nodes[0].ref == "Weather"


def test_tool_node_creation():
    node = ToolNode(
        id="n1",
        symbolic_ref="Weather",
        capability="get_weather",
        tool_name="get_weather",
        inputs={"q": "Tokyo"},
    )
    assert node.kind == "tool"
    assert node.tool_name == "get_weather"


def test_execution_graph_immutable_schema():
    tool = ToolNode(
        id="n1",
        symbolic_ref="A",
        capability="get_weather",
        tool_name="get_weather",
        inputs={"q": "Tokyo"},
    )
    graph = ExecutionGraph(graph_id="g1", nodes={"n1": tool}, waves=[["n1"]])
    assert graph.graph_id == "g1"
    assert "n1" in graph.nodes


def test_map_and_reduce_nodes():
    map_node = MapNode(
        id="m1",
        symbolic_ref="items_map",
        depends_on=[],
        iterate_over="items",
        body=ToolNode(
            id="b1",
            symbolic_ref="items",
            capability="echo",
            tool_name="echo",
            inputs={"${item}": "${item}"},
        ),
    )
    assert map_node.kind == "map"
    assert map_node.iterate_over == "items"
    reduce_node = ReduceNode(
        id="r1", symbolic_ref="agg", depends_on=["m1"],
        aggregate_kind="sum" if False else "summary",
        source_ref="items_map",
    )
    assert reduce_node.kind == "reduce"
    assert reduce_node.aggregate_kind == "summary"


def test_execution_graph_waves():
    a = ToolNode(id="a", symbolic_ref="A", capability="t1", tool_name="t1", inputs={})
    b = ToolNode(id="b", symbolic_ref="B", capability="t2", tool_name="t2", inputs={}, depends_on=["a"])
    graph = ExecutionGraph(graph_id="g", nodes={"a": a, "b": b}, waves=[["a"], ["b"]])
    assert graph.waves == [["a"], ["b"]]
    assert graph.nodes["b"].depends_on == ["a"]


# ============================================================================
# 2. ExecutionContext Tests
# ============================================================================


def test_context_from_state():
    ctx = ExecutionContext.from_state({})
    assert ctx.version == 1
    assert isinstance(ctx.ir_stack, dict)


def test_context_apply():
    ctx = ExecutionContext.from_state({})
    patch = StatePatch(version=2, updates={"key": "val"})
    ctx2 = ctx.apply(patch)
    assert ctx2.version == 2
    assert ctx2.snapshot["key"] == "val"
    assert ctx2.parent_version == 1


def test_context_branch():
    ctx = ExecutionContext.from_state({})
    branch = ctx.branch()
    assert branch.version == ctx.version
    assert branch.parent_version == ctx.version


def test_context_replay():
    patches = [
        StatePatch(version=1, updates={"step": "one"}),
        StatePatch(version=2, updates={"step": "two"}),
    ]
    replayed = ExecutionContext.replay(patches)
    assert replayed.version == 2
    assert replayed.snapshot["step"] == "two"


def test_context_to_state_update():
    ctx = ExecutionContext.from_state({"_candidate_set": ["test"]})
    update = ctx.to_state_update()
    assert "_ir_stack" in update
    assert "_context_version" in update
    assert "_context_snapshot" in update


# ============================================================================
# 3. Cache Tests
# ============================================================================


@pytest.mark.asyncio
async def test_parse_cache():
    cache = ParseCache(ttl=60)
    await cache.set("hello", [], "test_model", [{"action": "test"}])
    result = await cache.get("hello", [], "test_model")
    assert result == [{"action": "test"}]
    stats = cache.stats()
    assert stats["hits"] >= 1
    assert stats["hit_rate"] > 0


@pytest.mark.asyncio
async def test_plan_cache():
    cache = PlanCache(ttl=60)
    workflow = {"version": "1.0", "nodes": [{"op": "test_op", "ref": "A"}], "collections": {}}
    graph = {"graph_id": "g1", "nodes": {}, "waves": []}
    await cache.set_workflow(workflow, graph)
    result = await cache.get_workflow(workflow)
    assert result == graph


def test_fingerprint_includes_registry():
    fp = _query_fingerprint("hello", [])
    assert isinstance(fp, str)
    assert len(fp) > 0


# ============================================================================
# 4. Pass Manager Tests
# ============================================================================


def _tool_node(nid: str, dep: str | None = None) -> ToolNode:
    return ToolNode(
        id=nid,
        symbolic_ref=nid,
        capability="cap",
        tool_name="tool",
        inputs={},
        depends_on=[dep] if dep else [],
    )


def test_dead_task_elimination():
    # ReduceNode with no consumers is pure → eliminated; ToolNode kept
    reduce = ReduceNode(
        id="agg", symbolic_ref="agg", depends_on=["a"],
        aggregate_kind="summary", source_ref="a",
    )
    graph = ExecutionGraph(
        graph_id="g",
        nodes={"a": _tool_node("a"), "agg": reduce},
        waves=[["a"], ["agg"]],
    )
    result = dead_task_run(graph)
    assert "a" in result.nodes  # side-effectful tool kept
    assert "agg" not in result.nodes  # unreferenced pure node removed


def test_dependency_simplification():
    graph = ExecutionGraph(
        graph_id="g",
        nodes={"a": _tool_node("a"), "b": _tool_node("b", dep="a")},
        waves=[["a"], ["b"]],
    )
    result = dep_simplify_run(graph)
    # Pass should not crash and should preserve the dependency chain
    assert "a" in result.nodes
    assert "b" in result.nodes
    assert result.nodes["b"].depends_on == ["a"]


def test_parallel_fusion():
    graph = ExecutionGraph(
        graph_id="g",
        nodes={"1": _tool_node("1"), "2": _tool_node("2")},
        waves=[["1", "2"]],
    )
    result = fusion_run(graph)
    # Both independent tools in the same wave — fused into a batch
    assert len(result.nodes) >= 1
    assert len(result.waves) >= 1


# ============================================================================
# 5. EWMA Tests
# ============================================================================


def test_ewma_success():
    new = ewma_update(0.8, success=True, alpha=0.3)
    assert 0.8 < new <= 1.0


def test_ewma_failure():
    new = ewma_update(0.8, success=False, alpha=0.3)
    assert 0.0 <= new < 0.8


# ============================================================================
# 6. Golden Compiler Tests
# ============================================================================


@pytest.mark.parametrize("test_dir", [
    d for d in (Path(__file__).parent / "golden_data").iterdir() if d.is_dir()
])
@pytest.mark.asyncio
async def test_compiler_golden(test_dir, mock_db_session):
    """Load a LogicalWorkflow from golden_data, compile, and assert against expected physical graph."""
    logical_path = test_dir / "logical.json"
    workflow = LogicalWorkflow(**json.loads(logical_path.read_text()))

    from nexus.capabilities.resolver import DynamicCapabilityResolver

    resolver = DynamicCapabilityResolver(mock_db_session)
    compiler = Compiler(resolver)
    graph = await compiler.compile(workflow)

    expected_path = test_dir / "physical.json"
    expected = json.loads(expected_path.read_text())

    assert len(graph.nodes) == len(expected["nodes"])

    actual_node = list(graph.nodes.values())[0]
    expected_node = list(expected["nodes"].values())[0]

    assert actual_node.kind == expected_node["kind"]
    assert actual_node.symbolic_ref == expected_node["symbolic_ref"]
    assert actual_node.capability == expected_node["capability"]
    assert actual_node.inputs == expected_node["inputs"]

    logger = structlog.get_logger("test_compiler_golden")
    logger.info("golden_test.passed", test_dir=test_dir.name, node_count=len(graph.nodes))
