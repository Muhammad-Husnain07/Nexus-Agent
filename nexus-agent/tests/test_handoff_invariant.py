"""Permanent handoff gate — Executor → Artifact → Response invariant.

The class of bug that broke every domain (all-None artifacts, dead
artifact cache, synthesis discarding real data) must never return. This
suite is deterministic (no live server, no LLM) and runs in the normal
non-live CI gate:

    Executor Success
        → Artifact Registered
        → Artifact Contract Valid
        → Response References Artifact
        → PASS

Plus the P0 honest-failure propagation: validator/compiler aborts must
surface their reason in the final response (never the generic text).
"""

from __future__ import annotations

import pytest

from nexus.artifacts.normalizer import normalize_artifact

WEATHER_RAW = {
    "latitude": 35.7,
    "longitude": 139.6875,
    "current_weather": {
        "time": "2026-08-07T08:00",
        "interval": 900,
        "temperature": 29.5,
        "windspeed": 8.0,
        "winddirection": 175,
        "is_day": 1,
        "weathercode": 0,
    },
}
WEATHER_FLAT = {
    "latitude": "latitude",
    "longitude": "longitude",
    "temperature_c": "current_weather.temperature",
    "windspeed_kmh": "current_weather.windspeed",
    "weathercode": "current_weather.weathercode",
    "recorded_at": "current_weather.time",
}


class FakeTask:
    id = "task-handoff"
    tool_name = "get_current_weather"
    capability = "get_current_weather"


class FakeToolRead:
    name = "get_current_weather"
    category = "weather"
    output_schema = {
        "properties": {
            "latitude": {"type": "number"},
            "longitude": {"type": "number"},
            "current_weather": {"type": "object"},
            "is_day": {"type": "number"},
            "recorded_at": {"type": "string"},
            "weathercode": {"type": "number"},
        },
        "x-artifact-fields": WEATHER_FLAT,
        "x-artifact-optional": [],
    }


class _FakeResult:
    def __init__(self, data: dict) -> None:
        self.data = data
        self.status = "success"
        self.error = None


async def _register(executor, data: dict, session_id: str):
    from nexus.artifacts.graph import reset_artifact_graph

    reset_artifact_graph(session_id)
    return await executor._register_artifact(
        FakeTask(), _FakeResult(data), FakeToolRead(), exec_key="hk"
    )


@pytest.mark.asyncio
async def test_gate_executor_success_registers_artifact():
    """Executor success must produce a registered artifact (by execution id)."""
    from nexus.agent.executors.concurrent_executor import ConcurrentExecutor
    from nexus.artifacts.graph import get_artifact_graph

    executor = ConcurrentExecutor(session_id="gate-s1")
    await _register(executor, WEATHER_RAW, "gate-s1")
    artifacts = get_artifact_graph("gate-s1").all()
    assert len(artifacts) == 1, "successful execution must register an artifact"
    assert artifacts[0].execution_id == FakeTask.id
    assert artifacts[0].tool_name == "get_current_weather"


@pytest.mark.asyncio
async def test_gate_artifact_contract_valid():
    """Every declared x-artifact-fields path must resolve to a non-None value."""
    from nexus.agent.executors.concurrent_executor import ConcurrentExecutor
    from nexus.artifacts.graph import get_artifact_graph

    executor = ConcurrentExecutor(session_id="gate-s2")
    await _register(executor, WEATHER_RAW, "gate-s2")
    artifact = get_artifact_graph("gate-s2").all()[0]
    for key in WEATHER_FLAT:
        assert artifact.data.get(key) is not None, f"{key} failed to resolve"


@pytest.mark.asyncio
async def test_gate_all_none_rejected():
    """An all-None payload must never enter the artifact graph."""
    from nexus.agent.executors.concurrent_executor import ConcurrentExecutor
    from nexus.artifacts.graph import get_artifact_graph

    executor = ConcurrentExecutor(session_id="gate-s3")
    await _register(executor, {"latitude": None, "longitude": None}, "gate-s3")
    assert len(get_artifact_graph("gate-s3").all()) == 0, (
        "all-None payload must be rejected at registration"
    )


def test_gate_response_references_artifact():
    """The rendered answer must incorporate the registered artifact values."""
    from nexus.agent.nodes.response import _synthesis_incorporates_data
    from nexus.artifacts.base import ArtifactBase

    artifact = ArtifactBase(
        type="weather", tool_name="get_current_weather",
        data=normalize_artifact("w", WEATHER_RAW, flat_fields=WEATHER_FLAT),
    )
    rendered = "The temperature in Tokyo is 29.5 degrees Celsius"
    assert _synthesis_incorporates_data(rendered, [artifact]) is True
    lying = "I do not have any temperature information."
    assert _synthesis_incorporates_data(lying, [artifact]) is False


@pytest.mark.asyncio
async def test_gate_abort_reason_reaches_response():
    """P0: validator/compiler aborts must surface their reason — never the
    generic "I processed your request." text."""
    from nexus.agent.nodes.response import response_node

    state = {
        "session_id": "gate-s4",
        "errors": ["dependency cycle detected", "get_current_weather missing producer"],
        "_logical_workflow": None,
        "response_type": "",
    }
    result = await response_node(state, llm=None, model="m")  # no LLM needed
    final = result.get("final_response", "")
    assert "dependency cycle detected" in final, f"reason missing: {final}"
    assert result.get("response_type") == "error"
