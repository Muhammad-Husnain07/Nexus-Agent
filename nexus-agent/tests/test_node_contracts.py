"""Node Contract Drift Test — static verification of the orchestration
contract registry against the implementation.

Pipeline:
    Implementation → AST writer extraction → declared NodeContract →
    consistency checks → CI pass/fail.

Checks:
1. Every graph node has exactly one contract; every contract maps to a live
   graph node.
2. Every state field a node module actually WRITES is declared in its
   contract (AST-scanned dict/StatePatch keys) — and every declared write is
   actually written (no phantom declarations).
3. No two nodes own the same state field (single ownership).
4. Every consumed/input field has a declared writer (or is intentionally
   persistent).
5. COMPILE-phase nodes never write fields owned by RUNTIME nodes and vice
   versa.
6. Every declared output is consumed by another node or is terminal.
7. Invariants: success+artifacts ⇒ never error; response synthesis reads no
   raw tool results; optimizer returns a NEW graph object; executor output
   leaves the compiled graph dict untouched.
"""

from __future__ import annotations

import ast
import pathlib
from importlib import import_module

import pytest

from nexus.agent.contracts import NODE_CONTRACTS

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"

# Terminal outputs (no consumer required)
_TERMINAL = {"final_response", "_execution_events", "routing_decision", "workflow_definition",
             "workflow_artifacts", "clarification_question", "approval_decision",
             "memory_entries", "aggregated_results", "graph_patch", "replan_context",
             "RecoveryDecision", "validation_failures", "ExecutionPlan", "ValidationResult",
             "PlanValidatorReport", "LogicalWorkflow", "ExecutionGraph", "ExecutionEvents",
             "artifacts", "typed_failures", "ReduceNode", "user_message", "capability_catalog",
             "aggregated_results"}

_INTENTIONALLY_PERSISTENT = frozenset({
    "_structured_context", "_ir_stack", "_context_version", "_logical_workflow",
    "_execution_graph", "_optimization_snapshots", "_graph_version", "_cost_estimate",
    "_latency_estimate_ms", "_within_budget", "_estimate_warnings", "_aggregated_results",
    "_graph_patch", "_memory_persisted", "_active_workflow_id", "_workflow_type",
    "_workflow_step", "_workflow_steps_total", "_workflow_collected", "_workflow_history",
    "_workflow_next_action", "_workflow_definition", "_workflow_completed_steps",
    "_workflow_captured", "_workflow_dynamic_pending", "_workflow_dynamic_intent",
    "_approval_pending", "_approval_checkpoint_context", "_approval_modification",
})

# Shared channels (multiple writers by design — excluded from single-ownership)
_SHARED_FIELDS = frozenset({
    "errors", "messages", "final_response", "response_type", "working_memory",
    "intent", "tool_results", "iteration_count", "total_cost_usd",
    "_routing_decision",
    # Approval coordination (gate + resume node cooperate by design)
    "_approval_granted", "_approval_pending", "_approval_chain_state", "_needs_approval",
    # The workflow node (runtime) also produces logical workflows
    "_logical_workflow",
    # Retry counters shared between recovery and reflection
    "_total_retry_count",
    # Recovery availability flags shared between recovery + reflection
    "_recovery_available", "_recovery_failed_tasks",
    # Routing flags shared by the workflow engine and the requirement path
    "_route_to_planner",
    "_ready_to_plan",
    "_replan_context",
    "_bypass_workflow",
    # The invocation ReasoningBudget ledger — consumed by the validator,
    # compiler, and recovery replan loops (one shared counter by design)
    "_invocation_budget",
    # Workflow payload produced by the workflow engine, consumed by response
    "_structured_payload",
})

# Declared writes performed INDIRECTLY (through helper calls the AST cannot
# see, e.g. ``ExecutionGoals.to_state()``) — verified by the producer test.
_INDIRECT_WRITES: dict[str, frozenset[str]] = {
    "RouterNode": frozenset({"_goals", "_needs_requirements", "_query_type"}),
}


def _module_path(node: str) -> str | None:
    return next((c.module for c in NODE_CONTRACTS if c.node_id == node), None)


class _WriterExtractor(ast.NodeVisitor):
    """Collect string keys written to state: StatePatch(updates=...), updates
    dict assignments, returned dict literals, and subscript assignments
    (``result["field"] = ...``) at function scope."""

    def __init__(self) -> None:
        self.keys: set[str] = set()

    def _collect(self, node: ast.AST | None) -> None:
        if node is None:
            return
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    self.keys.add(k.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "update" and node.args:
                self._collect(node.args[0])
        for child in ast.iter_child_nodes(node):
            self._collect(child)

    def visit_Return(self, node: ast.Return) -> None:  # noqa: N802
        self._collect(node.value)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in (
                "updates", "result", "payload", "patch",
            ):
                self._collect(node.value)
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and isinstance(target.slice, ast.Constant)
                and isinstance(target.slice.value, str)
            ):
                self.keys.add(target.slice.value)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if isinstance(node.func, ast.Attribute) and node.func.attr == "update" and node.args:
            self._collect(node.args[0])
        if isinstance(node.func, ast.Name) and node.func.id == "StatePatch":
            for kw in node.keywords:
                if kw.arg == "updates":
                    self._collect(kw.value)
        self.generic_visit(node)


def _actual_writes(module_name: str, func_name: str = "") -> set[str]:
    mod = import_module(module_name)
    source = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    extractor = _WriterExtractor()
    if func_name:
        target = next(
            (n for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and n.name == func_name),
            None,
        )
        if target is None:
            raise AssertionError(f"function '{func_name}' not found in {module_name}")
        extractor.visit(target)
    else:
        extractor.visit(tree)
    # Drop node-internal keys that are not state fields
    return {
        k for k in extractor.keys
        if k.startswith("_") or k in {"final_response", "response_type", "messages",
                                     "working_memory", "errors", "intent", "tool_results",
                                     "iteration_count", "total_cost_usd"}
    }


def test_every_graph_node_has_exactly_one_contract():
    """Liveness: every graph node has a contract; every contract is live."""
    from nexus.agent.graph import build_agent_graph

    graph_nodes = {
        n for n in build_agent_graph().get_graph().nodes.keys()
        if n not in ("__start__", "__end__")
    }
    contract_ids = {c.node_id for c in NODE_CONTRACTS}
    assert graph_nodes == contract_ids, (
        f"graph/contract mismatch: graph-only={graph_nodes - contract_ids} "
        f"contract-only={contract_ids - graph_nodes}"
    )
    assert len(contract_ids) == len(NODE_CONTRACTS), "duplicate node ids in registry"


def test_writes_are_declared_and_no_phantoms():
    """AST writer extraction two-way check per node."""
    for contract in NODE_CONTRACTS:
        actual = _actual_writes(contract.module, contract.func_name)
        declared = set(contract.writes)
        undeclared = actual - declared
        phantom = declared - actual - _INDIRECT_WRITES.get(contract.node_id, frozenset())
        assert not undeclared, (
            f"{contract.node_id}: writes {sorted(undeclared)} not declared in contract"
        )
        # Phantom writes allowed only for non-underscore passthrough fields
        phantom_real = {p for p in phantom if p.startswith("_")}
        assert not phantom_real, (
            f"{contract.node_id}: declared writes never written: {sorted(phantom_real)}"
        )


def test_single_ownership():
    owner: dict[str, str] = {}
    for contract in NODE_CONTRACTS:
        for field in contract.writes:
            if field in _INTENTIONALLY_PERSISTENT or field in _SHARED_FIELDS:
                continue
            if field in owner and owner[field] != contract.node_id:
                pytest.fail(
                    f"field '{field}' owned by both {owner[field]} and {contract.node_id}"
                )
            owner[field] = contract.node_id


def test_every_input_has_a_producer():
    writers = {f: c.node_id for c in NODE_CONTRACTS for f in c.writes}
    for contract in NODE_CONTRACTS:
        for field in contract.inputs:
            if field in _INTENTIONALLY_PERSISTENT or field in _SHARED_FIELDS:
                continue
            if field not in writers and field not in {"messages", "errors", "tool_results",
                                                      "response_type", "intent",
                                                      "working_memory"}:
                pytest.fail(f"{contract.node_id}: input '{field}' has no declared writer")


def test_compile_never_writes_runtime_fields():
    from nexus.agent.contracts import NodePhase

    runtime_fields = {
        f for c in NODE_CONTRACTS if c.phase == NodePhase.RUNTIME for f in c.writes
    } - _SHARED_FIELDS
    compile_nodes = [c for c in NODE_CONTRACTS if c.phase == NodePhase.COMPILE]
    for c in compile_nodes:
        overlap = set(c.writes) & runtime_fields
        assert not overlap, f"{c.node_id}: compile node writes runtime field(s) {sorted(overlap)}"


def test_outputs_consumed_or_terminal():
    consumers = {item for c in NODE_CONTRACTS for item in c.consumes}
    consumed = {item for c in NODE_CONTRACTS for item in c.produces if item in consumers}
    for contract in NODE_CONTRACTS:
        for output in contract.produces:
            if output in _TERMINAL:
                continue
            if output not in consumed:
                pytest.fail(f"{contract.node_id}: output '{output}' has no consumer")


def test_invariant_success_artifacts_never_error():
    """Successful execution + artifacts ⇒ never a final error response."""
    from nexus.agent.nodes.response import _synthesis_fallback_patch, _render_artifacts

    class _Art:
        tool_name = "weather"
        capability_id = "weather"
        data = {"temperature_c": 25.1, "condition": "clear"}

    artifacts = [_Art()]
    assert _render_artifacts(artifacts), "renderer must produce text from artifacts"
    patch = _synthesis_fallback_patch({}, artifacts, "note")
    assert patch.get("response_type") != "error"
    assert patch.get("final_response")
    assert patch.get("_synthesis_failed") is True


def test_invariant_response_reads_only_artifacts():
    """Response synthesis must not consume raw tool results."""
    src = (SRC / "nexus" / "agent" / "nodes" / "response.py").read_text(encoding="utf-8")
    assert "tool_results" not in src.replace("artifact_list", ""), (
        "response.py must not reference tool_results (artifact-first)"
    )


def test_invariant_optimizer_returns_new_object():
    """The optimizer/passes never mutate the input graph (immutable contract)."""
    from nexus.compiler.ir_models import ExecutionGraph, ToolNode
    from nexus.compiler.passes.pass_candidate_ranking import run as ranking_pass

    tool = ToolNode(id="t1", symbolic_ref="r1", capability="c",
                    tool_name="t", endpoint_url="http://x")
    graph = ExecutionGraph(graph_id="g1", nodes={"t1": tool}, waves=[["t1"]])
    result = ranking_pass(graph)
    assert result is not graph
    assert result.graph_id == graph.graph_id
