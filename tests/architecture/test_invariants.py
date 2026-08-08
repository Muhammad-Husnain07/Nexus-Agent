"""Architecture fitness tests — CI guardrails against architectural drift.

These tests ensure the Agent OS architecture invariants are maintained:
1. ExecutionContext stays under 5KB when serialized
2. Agent nodes never import from nexus.registry directly
3. response_node never references tool_results or _executor_results
4. ArtifactGraph is used instead of raw JSON dicts
5. ExecutionPlan is immutable (frozen=True, extra='forbid')
"""

import ast
import os
import sys
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parent.parent.parent / "nexus-agent" / "src" / "nexus"


# ============================================================================
# Test 1: ExecutionContext serialized size < 5KB
# ============================================================================


class TestContextSize:
    """ExecutionContext must stay lean (< 5KB serialized)."""

    def test_execution_context_size(self) -> None:
        from nexus.execution.context import ExecutionContext

        ctx = ExecutionContext(
            version=42,
            parent_version=41,
            snapshot={"messages": [{"role": "user", "content": "hello"}], "final_response": "hi"},
            ir_stack={"version": "1.0", "operations": []},
            artifact_ids=["a1", "a2"],
            execution_ids=["e1"],
            routing_decision="finalize",
        )
        import json
        serialized = json.dumps(ctx.model_dump(mode="json"))
        size_kb = len(serialized) / 1024
        assert size_kb < 5, f"ExecutionContext too large: {size_kb:.2f}KB (limit 5KB)"


# ============================================================================
# Test 2: No direct registry imports in agent nodes
# ============================================================================


class TestNoRegistryImports:
    """Agent node files must NOT import from nexus.registry directly."""

    NODE_DIR = SRC_ROOT / "agent" / "nodes"

    def test_no_registry_imports(self) -> None:
        forbidden_prefixes = ("nexus.registry", "from nexus.registry")
        violations = []

        if not self.NODE_DIR.is_dir():
            pytest.skip(f"Node directory not found: {self.NODE_DIR}")

        for py_file in self.NODE_DIR.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
            content = py_file.read_text()
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if any(alias.name.startswith(p) for p in forbidden_prefixes):
                            violations.append(f"{py_file.name}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and any(node.module.startswith(p) for p in forbidden_prefixes):
                        violations.append(f"{py_file.name}: from {node.module} import ...")

        # Known pre-existing: optimizer_node, semantic_parser_node, validator_node
        # use RegistryClient pending migration to GlobalContext.  Fail only if
        # NEW violations appear beyond these known files.
        known_offenders = {"optimizer_node.py", "semantic_parser_node.py", "validator_node.py"}
        new_violations = [v for v in violations if not any(o in v for o in known_offenders)]
        assert not new_violations, (
            f"New direct registry imports found:\n" + "\n".join(new_violations)
        )


# ============================================================================
# Test 3: ResponseNode isolation — must not reference tool_results or _executor_results
# ============================================================================


class TestResponseNodeIsolation:
    """response_node.py must not reference tool_results or _executor_results."""

    RESPONSE_FILE = SRC_ROOT / "agent" / "nodes" / "response.py"

    def test_no_tool_results_reference(self) -> None:
        if not self.RESPONSE_FILE.is_file():
            pytest.skip(f"response.py not found: {self.RESPONSE_FILE}")
        content = self.RESPONSE_FILE.read_text()
        tree = ast.parse(content)
        violations = []
        # Only check actual code nodes, not docstrings or comments
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in ("tool_results", "_executor_results"):
                violations.append(f"Name reference '{node.id}' at line {node.lineno}")
            if isinstance(node, ast.Attribute) and node.attr in ("tool_results", "_executor_results"):
                violations.append(f"Attribute reference '.{node.attr}' at line {node.lineno}")
        assert not violations, (
            f"response.py references banned fields:\n" + "\n".join(violations)
        )


# ============================================================================
# Test 4: ArtifactGraph usage
# ============================================================================


class TestArtifactGraph:
    """Tool returns should be registered in ArtifactGraph, not returned as raw JSON."""

    def test_artifact_graph_basic(self) -> None:
        from nexus.artifacts.base import ArtifactBase
        from nexus.artifacts.graph import get_artifact_graph, reset_artifact_graph

        reset_artifact_graph()
        graph = get_artifact_graph()

        a = ArtifactBase(type="test", tool_name="test_tool", data={"key": "value"})
        graph.register(a)

        assert len(graph) == 1
        assert graph.get(a.artifact_id) is a
        assert len(graph.get_by_type("test")) == 1

        reset_artifact_graph()

    def test_artifact_base_extra_forbid(self) -> None:
        from nexus.artifacts.base import ArtifactBase
        from pydantic import ValidationError
        import pytest

        with pytest.raises(ValidationError):
            ArtifactBase(type="test", unknown_field="should_fail", data={})


# ============================================================================
# Test 5: ExecutionPlan immutability
# ============================================================================


class TestExecutionPlanImmutability:
    """ExecutionPlan must be frozen and forbid extra fields."""

    def test_execution_plan_frozen(self) -> None:
        from nexus.compiler.execution_plan import ExecutionPlan
        from pydantic import ValidationError
        import pytest

        plan = ExecutionPlan()
        with pytest.raises(ValidationError):
            plan.budget = 999.0  # type: ignore[misc]

    def test_execution_plan_extra_forbid(self) -> None:
        from pydantic import ValidationError
        import pytest

        with pytest.raises(ValidationError):
            from nexus.compiler.execution_plan import ExecutionPlan  # noqa: F811

            ExecutionPlan(unknown_field="should_fail")  # type: ignore[call-arg]


# ============================================================================
# Test 6: GlobalContext immutability
# ============================================================================


class TestGlobalContextImmutability:
    """GlobalContext must be frozen and forbid extra fields."""

    def test_global_context_frozen(self) -> None:
        from nexus.context.global_context import GlobalContext
        from pydantic import ValidationError
        import pytest

        gc = GlobalContext()
        with pytest.raises(ValidationError):
            gc.compiled_graph = "mutated"  # type: ignore[misc]


# ============================================================================
# Test 7: ResponseNode isolation — must not reference tool_results or internal hashes
# ============================================================================


class TestResponseNodeIsolation:
    """response_node.py must not reference tool_results or _executor_results."""

    RESPONSE_FILE = SRC_ROOT / "agent" / "nodes" / "response.py"

    def test_no_tool_results_reference(self) -> None:
        if not self.RESPONSE_FILE.is_file():
            pytest.skip(f"response.py not found: {self.RESPONSE_FILE}")
        content = self.RESPONSE_FILE.read_text()
        tree = ast.parse(content)
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in ("tool_results", "_executor_results"):
                violations.append(f"Name reference '{node.id}' at line {node.lineno}")
            if isinstance(node, ast.Attribute) and node.attr in ("tool_results", "_executor_results"):
                violations.append(f"Attribute reference '.{node.attr}' at line {node.lineno}")
        assert not violations, f"response.py references banned fields:\n" + "\n".join(violations)


# ============================================================================
# Test 8: No tools in state — AST check that no node reads available_tools from state
# ============================================================================


class TestNoToolsInState:
    """Agent nodes must NOT read available_tools from LangGraph state."""

    NODE_DIR = SRC_ROOT / "agent" / "nodes"

    def test_no_tools_in_state(self) -> None:
        banned_patterns = ('state.get("available_tools"', 'state.get(\'available_tools\'',
                           'state.get("available_tools ', 'state.get(\'available_tools ')
        violations = []

        if not self.NODE_DIR.is_dir():
            pytest.skip(f"Node directory not found: {self.NODE_DIR}")

        for py_file in self.NODE_DIR.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
            content = py_file.read_text()
            for line_no, line in enumerate(content.splitlines(), 1):
                for pattern in banned_patterns:
                    if pattern in line:
                        violations.append(f"{py_file.name}:{line_no}: {line.strip()[:80]}")
        assert not violations, (
            "Nodes reading available_tools from state:\n" + "\n".join(violations)
        )


# ============================================================================
# Test 9: No nesting — ExecutionContext snapshot must not contain _context_snapshot key
# ============================================================================


class TestNoSnapshotNesting:
    """ExecutionContext.snapshot must not contain _context_snapshot key (prevents Russian-doll bloat)."""

    def test_no_nesting(self) -> None:
        """Assert that from_state() strips nested _context_snapshot and banned fields."""
        from nexus.execution.context import ExecutionContext

        # Simulate a real LangGraph state dict with intentional nesting and bloat
        mock_state = {
            "messages": [],
            "_context_version": 5,
            "_context_snapshot": {
                "messages": [],
                "_context_snapshot": {
                    "messages": [],
                    "_context_snapshot": {"old": "data"},
                },
                "tool_results": [{"tool_name": "get_weather", "data": {"temp": 72}}],
            },
            "tool_results": [{"tool_name": "get_weather", "data": {"temp": 72}}],
            "available_tools": [{"name": "get_weather"}],
            "_routing_decision": "finalize",
        }

        ctx = ExecutionContext.from_state(mock_state)

        # Assert no Russian-doll nesting
        assert "_context_snapshot" not in ctx.snapshot, (
            "ExecutionContext.snapshot contains nested _context_snapshot — Russian-doll bloat!"
        )
        # Assert tool_results stripped
        assert "tool_results" not in ctx.snapshot, (
            "tool_results leaked into snapshot via from_state!"
        )
        # Assert available_tools stripped
        assert "available_tools" not in ctx.snapshot, (
            "available_tools leaked into snapshot via from_state!"
        )
