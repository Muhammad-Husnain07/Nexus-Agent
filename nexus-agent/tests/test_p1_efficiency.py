"""P1-A/P1-B tests: large-DAG timing instrumentation + empty-plan safety.

P1-A: per-wave duration capture flows into WaveCompleted events and the
benchmark's critical-path accounting (wall_time vs wave-sum — the
structural-serialization vs per-wave-slow distinction).

P1-B: an EXECUTABLE request that produces neither artifacts nor errors
must NEVER be answered as silent success ("I processed your request.") —
it must land in an explicit PLANNING_FAILED / EXECUTION_FAILED state.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ---------------------------------------------------------------------------
# P1-A: wave timing instrumentation
# ---------------------------------------------------------------------------

def test_execution_results_tracks_wave_durations():
    from nexus.agent.executors.concurrent_executor import ExecutionResults

    r = ExecutionResults()
    assert r.wave_durations_ms == []
    r.wave_durations_ms.append(120.5)
    r.wave_durations_ms.append(80.0)
    assert r.wave_durations_ms == [120.5, 80.0]


def test_wave_completed_event_carries_duration():
    from nexus.execution.events import emit_wave_completed

    import inspect

    sig = inspect.signature(emit_wave_completed)
    assert "duration_ms" in sig.parameters
    assert sig.parameters["duration_ms"].default == 0.0


def test_benchmark_wave_timing_keys():
    """The runner must report wave-sum vs wall-time (critical-path
    accounting) so a large DAG's slowness is attributable."""
    import inspect

    import nexus.agent.executors.concurrent_executor as ce
    import scripts.run_benchmark as rb

    src = inspect.getsource(rb.run_one)
    assert "wave_timing" in src
    assert "wave_sum_ms" in src
    assert "max_wave_ms" in src
    assert "wall_s" in src
    assert "wave_durations_ms" in inspect.getsource(ce.ExecutionResults)


# ---------------------------------------------------------------------------
# P1-B: empty-plan safety invariant
# ---------------------------------------------------------------------------

def _state(**overrides):
    state = {
        "messages": [{"role": "user", "content": "Find books by Jane Austen"}],
        "_query_type": "action",
        "errors": [],
        "_logical_workflow": {"nodes": []},
        "final_response": None,
    }
    state.update(overrides)
    return state


class _NoLLM:
    async def complete(self, **kwargs):
        return type("R", (), {"failed": True, "content": None, "error": "no llm"})()()


def test_executable_no_output_is_explicit_failure(monkeypatch):
    """P1-B: executable request, no artifacts, no errors → PLANNING_FAILED,
    never 'I processed your request.'"""
    import asyncio

    from nexus.agent.nodes import response as rn

    calls = {}

    async def fake_compile(state, artifact_list, model):
        calls["compiled"] = True
        return None, [{"role": "user", "content": "q"}]

    monkeypatch.setattr(rn, "_compile_and_render", fake_compile)
    monkeypatch.setattr(rn, "get_artifact_graph", lambda sid: type(
        "G", (), {"all": lambda self: []}
    )())
    monkeypatch.setattr(rn, "_last_user_message", lambda state: "Find books by Jane Austen")

    # The executable-no-output path fires BEFORE any LLM synthesis.
    state = _state()
    out = asyncio.run(rn.response_node(state, _NoLLM(), "model"))
    assert out["_response_status"] in ("PLANNING_FAILED", "EXECUTION_FAILED")
    assert "couldn't complete" in out["final_response"]
    assert "I processed your request." not in out["final_response"]


def test_conversational_no_output_is_not_failure():
    """A pure conversational request with no artifacts is NOT a failure —
    the empty-plan invariant only applies to executable requests."""
    import asyncio

    from nexus.agent.nodes import response as rn

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(rn, "get_artifact_graph", lambda sid: type(
        "G", (), {"all": lambda self: []}
    )())
    monkeypatch.setattr(rn, "_last_user_message", lambda state: "hi there how are you today")

    async def fake_complete(model=None, messages=None, **kw):
        return type("R", (), {"failed": False, "content": "Hello! I'm doing well, thank you for asking.", "error": None})()

    state = _state(_query_type="conversational")
    out = asyncio.run(rn.response_node(state, type("L", (), {"complete": fake_complete})(), "model"))
    assert out.get("_response_status", "SUCCESS") in ("SUCCESS", "")
    monkeypatch.undo()


def test_response_status_stamped_on_success_path():
    """SUCCESS / PARTIAL_SUCCESS stamped on the success return."""
    import asyncio

    from nexus.agent.nodes import response as rn

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(rn, "get_artifact_graph", lambda sid: type(
        "G", (), {"all": lambda self: [
            type("A", (), {
                "capability_id": "define_word", "tool_name": "define_word",
                "data": {"definition": "a cache is a storage layer"},
                "execution_id": "n1", "artifact_id": "a1", "schema_version": "1.0",
            })()
        ]}
    )())

    async def fake_compile(state, artifact_list, model):
        return None, [{"role": "user", "content": "Define cache."}]

    async def fake_complete(model=None, messages=None, **kw):
        return type("R", (), {"failed": False, "content": "A cache is a storage layer.", "error": None})()

    monkeypatch.setattr(rn, "_compile_and_render", fake_compile)
    monkeypatch.setattr(rn, "_last_user_message", lambda state: "Define cache.")
    monkeypatch.setattr(rn, "_synthesis_incorporates_data", lambda *a, **k: True)
    monkeypatch.setattr(rn, "_synthesis_covers_each_artifact", lambda *a, **k: True)
    monkeypatch.setattr(rn, "_is_degenerate", lambda t: False)

    state = _state(_query_type="action")
    out = asyncio.run(rn.response_node(state, type("L", (), {"complete": fake_complete})(), "model"))
    assert out.get("_response_status") in ("SUCCESS", "PARTIAL_SUCCESS")
    monkeypatch.undo()


# ---------------------------------------------------------------------------
# P1-C: nano extraction recovery — diagnosed, bounded, class-appropriate
# ---------------------------------------------------------------------------

def test_diagnose_empty_plan_class():
    from nexus.agent.nodes.semantic_parser_node import (
        _PLAN_FAILURE_EMPTY,
        _PLAN_FAILURE_LLM,
        _PLAN_FAILURE_SCHEMA,
        _PLAN_FAILURE_TIMEOUT,
        _diagnose_plan_failure,
    )

    assert _diagnose_plan_failure({"nodes": []}, "", []) == _PLAN_FAILURE_EMPTY
    assert _diagnose_plan_failure({"nodes": []}, "timeout", []) == _PLAN_FAILURE_EMPTY
    assert _diagnose_plan_failure(None, "Request timed out.", []) == _PLAN_FAILURE_TIMEOUT
    assert _diagnose_plan_failure(None, "rate limit", []) == _PLAN_FAILURE_LLM
    assert _diagnose_plan_failure({"nodes": [{"op": "x"}]}, "", []) == _PLAN_FAILURE_SCHEMA


def test_repair_empty_plan_constrains_to_valid_ops():
    import asyncio

    from nexus.agent.nodes.semantic_parser_node import _repair_empty_plan

    class _Budget:
        def consume(self, name):
            return True

    class _Resp:
        failed = False
        error = None
        content = '{"nodes": [{"op": "invented_tool", "ref": "a"}, {"op": "get_current_weather", "ref": "b"}]}'

    class _LLM:
        async def complete(self, **kw):
            return _Resp()

    out = asyncio.run(_repair_empty_plan(
        _LLM(), "model", "weather in Lahore",
        ["get the weather for Lahore"],
        "catalog", ["get_current_weather", "geocode_location"],
        _Budget(),
    ))
    assert out is not None
    ops = [n["op"] for n in out["nodes"]]
    assert "get_current_weather" in ops
    assert "invented_tool" not in ops  # constrained to the registered set


def test_repair_empty_plan_returns_none_on_bad_json():
    import asyncio

    from nexus.agent.nodes.semantic_parser_node import _repair_empty_plan

    class _Budget:
        def consume(self, name):
            return True

    class _Resp:
        failed = False
        error = None
        content = "not json at all"

    class _LLM:
        async def complete(self, **kw):
            return _Resp()

    out = asyncio.run(_repair_empty_plan(
        _LLM(), "model", "weather",
        ["get the weather"], "", ["get_current_weather"], _Budget(),
    ))
    assert out is None


def test_repair_empty_plan_requires_units_and_budget():
    import asyncio

    from nexus.agent.nodes.semantic_parser_node import _repair_empty_plan

    class _Budget:
        def consume(self, name):
            return False

    out = asyncio.run(_repair_empty_plan(
        None, "model", "q", ["unit"], "", ["op"], _Budget(),
    ))
    assert out is None
    out2 = asyncio.run(_repair_empty_plan(
        None, "model", "q", [], "", ["op"],
        type("B", (), {"consume": lambda self, n: True})(),
    ))
    assert out2 is None


# ---------------------------------------------------------------------------
# P1-D: map/fan-out collapse — independent same-capability entity instances
# → ONE Map node + a declared collection (the reviewer's D48 abstraction)
# ---------------------------------------------------------------------------

def test_map_collapse_three_meals_into_one_map():
    from nexus.agent.nodes.semantic_parser_node import _collapse_map_candidates

    nodes = [
        {"op": "search_meals", "ref": "m1", "inputs": {"query": "chicken"}, "depends_on": []},
        {"op": "search_meals", "ref": "m2", "inputs": {"query": "pasta"}, "depends_on": []},
        {"op": "search_meals", "ref": "m3", "inputs": {"query": "rice"}, "depends_on": []},
    ]
    collapsed, collections = _collapse_map_candidates(nodes)
    assert len(collapsed) == 1
    map_node = collapsed[0]
    assert map_node["op"] == "search_meals"
    assert map_node["iterate_over"] == "search_meals_items"
    assert map_node["inputs"]["query"] == "${item}"
    assert collections["search_meals_items"] == ["chicken", "pasta", "rice"]


def test_map_collapse_skips_different_ops():
    from nexus.agent.nodes.semantic_parser_node import _collapse_map_candidates

    nodes = [
        {"op": "search_meals", "ref": "m1", "inputs": {"query": "chicken"}, "depends_on": []},
        {"op": "search_books", "ref": "b1", "inputs": {"query": "Austen"}, "depends_on": []},
    ]
    collapsed, collections = _collapse_map_candidates(nodes)
    assert len(collapsed) == 2
    assert collections == {}


def test_map_collapse_skips_nodes_with_dependencies():
    from nexus.agent.nodes.semantic_parser_node import _collapse_map_candidates

    nodes = [
        {"op": "search_meals", "ref": "m1", "inputs": {"query": "chicken"}, "depends_on": ["g1"]},
        {"op": "search_meals", "ref": "m2", "inputs": {"query": "pasta"}, "depends_on": ["g1"]},
        {"op": "search_meals", "ref": "m3", "inputs": {"query": "rice"}, "depends_on": []},
    ]
    collapsed, collections = _collapse_map_candidates(nodes)
    # m1/m2 share deps and are map-compatible; m3 differs → untouched.
    assert len(collapsed) == 2  # 1 map (m1+m2) + 1 passthrough (m3)
    assert collections.get("search_meals_items") == ["chicken", "pasta"]


def test_map_collapse_skips_multiple_varying_params():
    from nexus.agent.nodes.semantic_parser_node import _collapse_map_candidates

    nodes = [
        {"op": "get_current_weather", "ref": "w1",
         "inputs": {"latitude": 31.5, "longitude": 74.3}, "depends_on": []},
        {"op": "get_current_weather", "ref": "w2",
         "inputs": {"latitude": 31.5, "longitude": 74.4}, "depends_on": []},
    ]
    collapsed, collections = _collapse_map_candidates(nodes)
    assert len(collapsed) == 2  # two varying numeric params — not a map
    assert collections == {}


def test_map_collapse_skips_duplicate_values():
    from nexus.agent.nodes.semantic_parser_node import _collapse_map_candidates

    nodes = [
        {"op": "search_meals", "ref": "m1", "inputs": {"query": "chicken"}, "depends_on": []},
        {"op": "search_meals", "ref": "m2", "inputs": {"query": "chicken"}, "depends_on": []},
    ]
    collapsed, collections = _collapse_map_candidates(nodes)
    assert len(collapsed) == 2  # same value twice — not distinct entities
    assert collections == {}
