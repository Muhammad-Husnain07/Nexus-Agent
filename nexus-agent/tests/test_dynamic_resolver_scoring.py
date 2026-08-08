"""Tests for DynamicCapabilityResolver, SchemaMatcher, and candidate ranking pass."""

from __future__ import annotations

from nexus.capabilities.schema_matcher import SchemaMatcher
from nexus.compiler.ir_models import ExecutionGraph, MapNode, ToolNode
from nexus.compiler.passes.pass_candidate_ranking import run as ranking_pass


class _MockCap:
    def __init__(self, consumes: list[str] | None = None) -> None:
        self.consumes = consumes or []


class _MockProvider:
    def __init__(self, consumes: list[str] | None = None) -> None:
        self.capability = _MockCap(consumes=consumes)


class _MockEndpoint:
    def __init__(self, consumes: list[str] | None = None) -> None:
        self.provider = _MockProvider(consumes=consumes)


class TestSchemaMatcher:
    """SchemaMatcher unit tests — pure, no DB or LLM."""

    def test_exact_match(self) -> None:
        endpoint = _MockEndpoint(consumes=["lat", "lon"])
        score = SchemaMatcher.compute(endpoint, {"lat": 35, "lon": 139})
        assert score == 1.0, f"Expected 1.0, got {score}"

    def test_partial_match(self) -> None:
        endpoint = _MockEndpoint(consumes=["lat", "lon"])
        score = SchemaMatcher.compute(endpoint, {"lat": 35})
        assert score == 0.5, f"Expected 0.5, got {score}"

    def test_no_overlap(self) -> None:
        endpoint = _MockEndpoint(consumes=["lat", "lon"])
        score = SchemaMatcher.compute(endpoint, {"city": "Tokyo"})
        assert score == 0.0, f"Expected 0.0, got {score}"

    def test_no_consumes_declared(self) -> None:
        endpoint = _MockEndpoint(consumes=[])
        score = SchemaMatcher.compute(endpoint, {"x": 1})
        assert score == 1.0, f"Expected 1.0, got {score}"

    def test_empty_inputs_shape(self) -> None:
        endpoint = _MockEndpoint(consumes=["lat", "lon"])
        score = SchemaMatcher.compute(endpoint, {})
        assert score == 0.5, f"Expected 0.5, got {score}"


class TestCandidateRankingPass:
    """candidate_ranking pass unit tests — pure, no I/O."""

    def test_primary_endpoint_always_included(self) -> None:
        tool = ToolNode(
            id="t1",
            symbolic_ref="r1",
            capability="test",
            tool_name="test",
            endpoint_url="http://primary.com",
        )
        graph = ExecutionGraph(graph_id="g1", nodes={"t1": tool}, waves=[["t1"]])
        result = ranking_pass(graph)
        node = result.nodes["t1"]
        urls = [c["url"] for c in node.candidate_endpoints]
        assert "http://primary.com" in urls, "Primary URL must be in candidates"

    def test_existing_candidates_merged(self) -> None:
        tool = ToolNode(
            id="t1",
            symbolic_ref="r1",
            capability="test",
            tool_name="test",
            endpoint_url="http://primary.com",
            candidate_endpoints=[{"url": "http://alt.com", "score": 0.8}],
        )
        graph = ExecutionGraph(graph_id="g1", nodes={"t1": tool}, waves=[["t1"]])
        result = ranking_pass(graph)
        urls = [c["url"] for c in result.nodes["t1"].candidate_endpoints]
        assert "http://primary.com" in urls, "Primary in candidates"
        assert "http://alt.com" in urls, "Alt in candidates"

    def test_no_duplicate_urls(self) -> None:
        tool = ToolNode(
            id="t1",
            symbolic_ref="r1",
            capability="test",
            tool_name="test",
            endpoint_url="http://dupe.com",
            candidate_endpoints=[{"url": "http://dupe.com", "score": 1.0}],
        )
        graph = ExecutionGraph(graph_id="g1", nodes={"t1": tool}, waves=[["t1"]])
        result = ranking_pass(graph)
        urls = [c["url"] for c in result.nodes["t1"].candidate_endpoints]
        assert urls.count("http://dupe.com") == 1, "Should deduplicate URLs"

    def test_map_node_body_candidates(self) -> None:
        body = ToolNode(
            id="b1",
            symbolic_ref="map_body",
            capability="test",
            tool_name="test",
            endpoint_url="http://primary.com",
            candidate_endpoints=[{"url": "http://alt.com", "score": 0.8}],
        )
        map_node = MapNode(
            id="m1",
            symbolic_ref="map",
            depends_on=[],
            iterate_over="items",
            body=body,
        )
        graph = ExecutionGraph(graph_id="g1", nodes={"m1": map_node}, waves=[["m1"]])
        result = ranking_pass(graph)
        urls = [c["url"] for c in result.nodes["m1"].body.candidate_endpoints]
        assert "http://primary.com" in urls, "Map body primary in candidates"
        assert "http://alt.com" in urls, "Map body alt in candidates"
