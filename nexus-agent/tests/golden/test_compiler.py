"""Golden compiler tests — snapshot-based regression prevention.

Each test subdirectory under ``tests/golden_data/`` contains:
- ``logical.json`` — input ``LogicalWorkflow``
- ``physical.json`` — expected ``ExecutionGraph`` output (UUIDs replaced with ``IGNORE_UUID``)

Tests compile the logical workflow and assert structural equality,
ignoring non-deterministic UUID/graph_id fields.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus.compiler.codegen import Compiler
from nexus.compiler.ir_models import LogicalWorkflow
from nexus.capabilities.resolver import DynamicCapabilityResolver

TEST_DATA_DIR = Path(__file__).parent.parent / "golden_data"


@pytest.mark.parametrize("test_dir", [
    d for d in TEST_DATA_DIR.iterdir() if d.is_dir()
])
@pytest.mark.asyncio
async def test_compiler_golden(test_dir: Path, mock_db_session: object) -> None:
    """Load a LogicalWorkflow, compile, and assert structural equality."""
    logical_path = test_dir / "logical.json"
    workflow = LogicalWorkflow(**json.loads(logical_path.read_text()))

    resolver = DynamicCapabilityResolver(mock_db_session)
    compiler = Compiler(resolver)
    graph = await compiler.compile(workflow)

    expected_path = test_dir / "physical.json"
    expected = json.loads(expected_path.read_text())

    assert len(graph.nodes) == len(expected["nodes"]), (
        f"Node count mismatch: {len(graph.nodes)} vs {len(expected['nodes'])}"
    )

    actual = list(graph.nodes.values())[0]
    exp_node = list(expected["nodes"].values())[0]

    assert actual.kind == exp_node["kind"], f"kind: {actual.kind} != {exp_node['kind']}"
    assert actual.symbolic_ref == exp_node["symbolic_ref"], f"ref: {actual.symbolic_ref} != {exp_node['symbolic_ref']}"
    assert actual.capability == exp_node["capability"], f"cap: {actual.capability} != {exp_node['capability']}"
    assert actual.tool_name == exp_node["tool_name"], f"tool: {actual.tool_name} != {exp_node['tool_name']}"
    assert actual.endpoint_url == exp_node.get("endpoint_url", ""), f"url: {actual.endpoint_url} != {exp_node.get('endpoint_url')}"
    assert actual.http_method == exp_node.get("http_method", "GET"), f"method: {actual.http_method} != {exp_node.get('http_method')}"
    assert actual.inputs == exp_node["inputs"], f"inputs: {actual.inputs} != {exp_node['inputs']}"
