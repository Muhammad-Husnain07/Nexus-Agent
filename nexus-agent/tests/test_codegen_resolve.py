"""RESOLVE(...) producer-chain synthesis tests (P0) — the compiler must
deterministically translate a declarative chain expression into a producer
node + a rewritten placeholder, never a guessed literal.
"""

from __future__ import annotations

import asyncio

from nexus.compiler.codegen import Compiler
from nexus.compiler.ir_models import LogicalNode, LogicalWorkflow


class _FakeResolver:
    async def resolve(self, op: str, context=None):
        if op == "geocode_location":
            return [_FakeCandidate("https://geocode.example.com")]
        return []


class _FakeCandidate:
    def __init__(self, url: str) -> None:
        self.url = url
        self.http_method = "GET"
        self.cost_per_call = 0.0
        self.latency_p99_ms = 100
        self.model_dump = lambda: {}


def _fake_gc(monkeypatch):
    class _GC:
        capability_index = {
            "geocode_location": {
                "produces": ["location", "latitude", "longitude"],
                "input_required": ["location"],
                "input_schema": {
                    "type": "object",
                    "properties": {"location": {"type": "string"}},
                },
            },
            "get_current_weather": {
                "produces": ["temperature", "current_weather"],
                "input_required": ["latitude", "longitude"],
                "input_schema": {"type": "object", "properties": {}},
            },
        }
        capability_keywords = {}
        capability_providers = {}
        alias_index = {}

        def match_capabilities(self, tokens):
            return []

    monkeypatch.setattr(
        "nexus.context.global_context.get_global_context", lambda: _GC()
    )


def test_resolve_expression_synthesizes_producer(monkeypatch):
    _fake_gc(monkeypatch)
    workflow = LogicalWorkflow(
        version="1.0",
        nodes=[
            LogicalNode(
                op="get_current_weather",
                ref="StepWeather",
                inputs={
                    "latitude": 'RESOLVE("geocode_location", "location", "Tokyo")',
                    "longitude": 'RESOLVE("geocode_location", "location", "Tokyo")',
                },
                depends_on=[],
            ),
        ],
        collections={},
    )
    compiler = Compiler(_FakeResolver())
    synthesized = asyncio.run(compiler._synthesize_resolve_producers(workflow))

    ops = {n.op for n in synthesized.nodes}
    assert "geocode_location" in ops, "producer must be synthesized"
    assert any("Tokyo" in str(n.inputs) for n in synthesized.nodes), (
        "producer must carry the user value"
    )
    weather = next(n for n in synthesized.nodes if n.op == "get_current_weather")
    assert weather.inputs["latitude"].startswith("${StepWeather_producer_"), (
        "consumer input must be rewritten to a placeholder"
    )
    assert any(dep.startswith("StepWeather_producer_") for dep in weather.depends_on), (
        "dependency must be wired"
    )
