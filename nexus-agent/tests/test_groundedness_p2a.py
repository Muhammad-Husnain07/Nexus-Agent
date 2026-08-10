"""P2-A GROUNDEDNESS gate — the response cannot claim tool-backed success on
LLM say-so: evidence credit is deterministic and artifact-derived.

The three pillars under test:

1. QUERY-TAINT EXCLUSION (P2-A): a scalar that appears in the user's own
   query text earns NO evidence credit — a response that merely echoes the
   request back ("Tokyo") does not count as engaging the artifact. The
   response must cite at least one ARTIFACT-derived (non-tainted) value.
2. PER-ARTIFACT REQUIRED-FACT: EVERY artifact needs ≥1 non-tainted cited
   value; the deterministic renderer (which renders every artifact) is the
   floor whenever an LLM text fails this — including after the
   degenerate-retry loop replaced the guarded text.
3. OPTIONAL CLAIM→ENTAILMENT (feature flag, default OFF): never the
   authority — it runs only after the deterministic guard, its NO degrades
   to the same renderer floor, and its error keeps the guarded response.

Planner behavior is FROZEN during P2-A by design (no planner edits).
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

import pytest

from nexus.artifacts.normalizer import normalize_artifact


class FakeTask:
    id = "task-p2a"
    tool_name = "city_weather"
    capability = "city_weather"


class FakeToolRead:
    name = "city_weather"
    category = "weather"
    output_schema = {
        "properties": {
            "city": {"type": "string"},
            "temperature_c": {"type": "number"},
            "population": {"type": "number"},
        },
        "x-artifact-fields": {
            "city": "city",
            "temperature_c": "temperature_c",
            "population": "population",
        },
        "x-artifact-optional": [],
    }


class _FakeResult:
    def __init__(self, data: dict) -> None:
        self.data = data
        self.status = "success"
        self.error = None


class _Complete:
    def __init__(self, content: str, failed: bool = False, error: str | None = None):
        self.content = content
        self.failed = failed
        self.error = error


class _FakeLLM:
    """Queue-driven fake: synthesis responses first, then optional verifier.

    ``complete`` is async (mirrors LLMClient), records its call count, and
    can raise (entailment error path).
    """

    def __init__(
        self,
        contents: list[str],
        failures: list[bool] | None = None,
        raise_on: set[int] | None = None,
    ):
        self.contents = list(contents)
        self.failures = list(failures or [False] * len(contents))
        self.raise_on = raise_on or set()
        self.calls = 0

    async def complete(self, **kwargs: Any) -> _Complete:
        idx = self.calls
        self.calls += 1
        if idx in self.raise_on:
            raise RuntimeError("fake llm failure")
        if idx >= len(self.contents):
            return _Complete("", failed=True, error="queue exhausted")
        return _Complete(self.contents[idx], failed=self.failures[idx])


async def _register(session_id: str, data: dict) -> None:
    from nexus.agent.executors.concurrent_executor import ConcurrentExecutor
    from nexus.artifacts.graph import reset_artifact_graph

    reset_artifact_graph(session_id)
    executor = ConcurrentExecutor(session_id=session_id)
    await executor._register_artifact(
        FakeTask(), _FakeResult(data), FakeToolRead(), exec_key="p2a"
    )


def _state(session_id: str, query: str) -> dict:
    return {
        "session_id": session_id,
        "messages": [{"role": "user", "content": query}],
        "_logical_workflow": {"nodes": [{"id": "n1"}]},
        "errors": [],
        "response_type": "",
        "working_memory": {"entries": []},
        "final_response": None,
        "_budget_exceeded": None,
    }


def _artifact(**data: Any):
    from nexus.artifacts.base import ArtifactBase

    return ArtifactBase(
        type="city_weather",
        tool_name="city_weather",
        data=normalize_artifact(
            "city_weather", data, flat_fields={k: k for k in data}
        ),
    )


# ============================================================================
# 1. QUERY-TAINT EXCLUSION (pure-function level)
# ============================================================================


def test_query_echo_earns_no_credit():
    from nexus.agent.nodes.response import _synthesis_incorporates_data

    art = _artifact(city="Tokyo", temperature_c=28.8)
    query = "What is the weather in Tokyo?"
    assert _synthesis_incorporates_data("Tokyo.", [art], user_query=query) is False
    assert _synthesis_incorporates_data("Tokyo", [art], user_query=query) is False


def test_non_tainted_value_still_counts():
    from nexus.agent.nodes.response import _synthesis_incorporates_data

    art = _artifact(city="Tokyo", temperature_c=28.8)
    query = "What is the weather in Tokyo?"
    assert _synthesis_incorporates_data("It is 28.8 degrees.", [art], user_query=query) is True


def test_mixed_tainted_and_clean_counts_via_clean():
    from nexus.agent.nodes.response import _synthesis_incorporates_data

    art = _artifact(city="Tokyo", temperature_c=28.8)
    query = "What is the weather in Tokyo?"
    assert (
        _synthesis_incorporates_data("Tokyo is 28.8 degrees.", [art], user_query=query)
        is True
    )


def test_artifact_with_only_tainted_value_never_covered():
    from nexus.agent.nodes.response import _synthesis_incorporates_data

    art = _artifact(city="Tokyo")
    query = "What is the weather in Tokyo?"
    assert _synthesis_incorporates_data("Tokyo", [art], user_query=query) is False


def test_empty_query_preserves_legacy_credit():
    from nexus.agent.nodes.response import _synthesis_incorporates_data

    art = _artifact(city="Tokyo")
    assert _synthesis_incorporates_data("Tokyo", [art], user_query="") is True


def test_taint_rule_respects_frozen_payloads():
    from nexus.agent.nodes.response import _synthesis_incorporates_data

    art = _artifact(city="Tokyo", temperature_c=28.8)
    frozen = MappingProxyType(dict(art.data))
    from nexus.artifacts.base import ArtifactBase

    frozen_art = ArtifactBase(type="city_weather", tool_name="city_weather", data=frozen)
    query = "What is the weather in Tokyo?"
    assert _synthesis_incorporates_data("Tokyo", [frozen_art], user_query=query) is False
    assert _synthesis_incorporates_data("28.8", [frozen_art], user_query=query) is True


def test_covers_each_requires_untainted_per_artifact():
    from nexus.agent.nodes.response import _synthesis_covers_each_artifact

    a = _artifact(city="Tokyo", temperature_c=28.8)
    b = _artifact(city="Osaka", population=125000000)
    query = "What is the weather in Tokyo and Osaka?"
    # Osaka's population is cited; Tokyo only echoed via the tainted query
    # entity "Tokyo" (temperature 28.8 NOT cited) → Tokyo uncovered.
    assert (
        _synthesis_covers_each_artifact(
            "Osaka has population 125000000.", [a, b], user_query=query
        )
        is False
    )
    assert (
        _synthesis_covers_each_artifact(
            "Tokyo is 28.8 degrees and Osaka has population 125000000.",
            [a, b],
            user_query=query,
        )
        is True
    )


def test_covered_count_metric_matches_guard():
    from nexus.agent.nodes.response import _covered_artifacts

    a = _artifact(city="Tokyo")
    b = _artifact(city="Osaka", population=125000000)
    query = "What is the weather in Tokyo and Osaka?"
    # Only Osaka covered — Tokyo's sole value "Tokyo" is query-tainted.
    assert _covered_artifacts("Osaka has population 125000000.", [a, b], user_query=query) == 1


# ============================================================================
# 2. END-TO-END: deterministic floor on the final text
# ============================================================================


@pytest.mark.asyncio
async def test_e2e_query_echo_response_renders_deterministically(monkeypatch):
    from nexus.agent.nodes import response as resp

    await _register("p2a-e2e-1", {"city": "Tokyo", "temperature_c": 28.8, "population": 1234567})

    async def _fake_compile(state, artifact_list, model):
        return (None, [{"role": "user", "content": "compiled"}])

    monkeypatch.setattr(resp, "_compile_and_render", _fake_compile)
    llm = _FakeLLM(["Tokyo."])
    result = await resp.response_node(_state("p2a-e2e-1", "What is the weather in Tokyo?"), llm=llm, model="m")
    final = result.get("final_response", "")
    assert final.startswith("I retrieved the following results:"), final
    assert "28.8" in final


@pytest.mark.asyncio
async def test_e2e_good_synthesis_stands(monkeypatch):
    from nexus.agent.nodes import response as resp

    await _register("p2a-e2e-2", {"city": "Tokyo", "temperature_c": 28.8, "population": 1234567})

    async def _fake_compile(state, artifact_list, model):
        return (None, [{"role": "user", "content": "compiled"}])

    monkeypatch.setattr(resp, "_compile_and_render", _fake_compile)
    llm = _FakeLLM(["The temperature in Tokyo is 28.8 degrees Celsius."])
    result = await resp.response_node(_state("p2a-e2e-2", "What is the weather in Tokyo?"), llm=llm, model="m")
    assert result.get("final_response") == "The temperature in Tokyo is 28.8 degrees Celsius."
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_e2e_retry_replacement_rechecked_deterministically(monkeypatch):
    """The degenerate-retry loop can REPLACE the guarded text — the P2-A
    post-retry re-check must catch a retried response that ignores artifacts."""
    from nexus.agent.nodes import response as resp

    await _register("p2a-e2e-3", {"city": "Tokyo", "temperature_c": 28.8, "population": 1234567})

    async def _fake_compile(state, artifact_list, model):
        return (None, [{"role": "user", "content": "compiled"}])

    monkeypatch.setattr(resp, "_compile_and_render", _fake_compile)
    # First answer "28.8" is degenerate (<40 chars) yet passes the first
    # guard (clean scalar); the retry is long but ignores all artifacts.
    llm = _FakeLLM(["28.8", "This response is long and conversational but contains no tool data whatsoever."])
    result = await resp.response_node(_state("p2a-e2e-3", "What is the weather in Tokyo?"), llm=llm, model="m")
    final = result.get("final_response", "")
    assert final.startswith("I retrieved the following results:"), final
    assert "28.8" in final


# ============================================================================
# 3. OPTIONAL CLAIM→ENTAILMENT VERIFIER (feature flag, default OFF)
# ============================================================================


def _flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from nexus.config.settings import get_settings as _real_get

    real = _real_get()
    patched = real.model_copy(
        update={
            "agent": real.agent.model_copy(
                update={"enable_claim_entailment": True}
            )
        }
    )
    monkeypatch.setattr("nexus.agent.nodes.response.get_settings", lambda: patched)


@pytest.mark.asyncio
async def test_e2e_entailment_off_by_default_single_call(monkeypatch):
    from nexus.agent.nodes import response as resp

    await _register("p2a-e2e-4", {"city": "Tokyo", "temperature_c": 28.8, "population": 1234567})

    async def _fake_compile(state, artifact_list, model):
        return (None, [{"role": "user", "content": "compiled"}])

    monkeypatch.setattr(resp, "_compile_and_render", _fake_compile)
    llm = _FakeLLM(["The temperature in Tokyo is 28.8 degrees Celsius."])
    result = await resp.response_node(_state("p2a-e2e-4", "What is the weather in Tokyo?"), llm=llm, model="m")
    assert result.get("final_response") == "The temperature in Tokyo is 28.8 degrees Celsius."
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_e2e_entailment_no_degrades_to_renderer(monkeypatch):
    from nexus.agent.nodes import response as resp

    await _register("p2a-e2e-5", {"city": "Tokyo", "temperature_c": 28.8, "population": 1234567})
    _flag_on(monkeypatch)

    async def _fake_compile(state, artifact_list, model):
        return (None, [{"role": "user", "content": "compiled"}])

    monkeypatch.setattr(resp, "_compile_and_render", _fake_compile)
    # Synthesis passes the deterministic guard; the VERIFIER says NO.
    llm = _FakeLLM(["The temperature in Tokyo is 28.8 degrees Celsius.", "NO"])
    result = await resp.response_node(_state("p2a-e2e-5", "What is the weather in Tokyo?"), llm=llm, model="m")
    final = result.get("final_response", "")
    assert final.startswith("I retrieved the following results:"), final
    assert "28.8" in final


@pytest.mark.asyncio
async def test_e2e_entailment_yes_keeps_response(monkeypatch):
    from nexus.agent.nodes import response as resp

    await _register("p2a-e2e-6", {"city": "Tokyo", "temperature_c": 28.8, "population": 1234567})
    _flag_on(monkeypatch)

    async def _fake_compile(state, artifact_list, model):
        return (None, [{"role": "user", "content": "compiled"}])

    monkeypatch.setattr(resp, "_compile_and_render", _fake_compile)
    llm = _FakeLLM(["The temperature in Tokyo is 28.8 degrees Celsius.", "YES"])
    result = await resp.response_node(_state("p2a-e2e-6", "What is the weather in Tokyo?"), llm=llm, model="m")
    assert result.get("final_response") == "The temperature in Tokyo is 28.8 degrees Celsius."
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_e2e_entailment_error_keeps_guarded_response(monkeypatch):
    """An optional verifier must never break a deterministic-guarded pass:
    its error → keep the response (it is NOT the authority)."""
    from nexus.agent.nodes import response as resp

    await _register("p2a-e2e-7", {"city": "Tokyo", "temperature_c": 28.8, "population": 1234567})
    _flag_on(monkeypatch)

    async def _fake_compile(state, artifact_list, model):
        return (None, [{"role": "user", "content": "compiled"}])

    monkeypatch.setattr(resp, "_compile_and_render", _fake_compile)
    llm = _FakeLLM(
        ["The temperature in Tokyo is 28.8 degrees Celsius."],
        raise_on={1},
    )
    result = await resp.response_node(_state("p2a-e2e-7", "What is the weather in Tokyo?"), llm=llm, model="m")
    assert result.get("final_response") == "The temperature in Tokyo is 28.8 degrees Celsius."


@pytest.mark.asyncio
async def test_e2e_entailment_verifier_failed_llm_keeps_response(monkeypatch):
    from nexus.agent.nodes import response as resp

    await _register("p2a-e2e-8", {"city": "Tokyo", "temperature_c": 28.8, "population": 1234567})
    _flag_on(monkeypatch)

    async def _fake_compile(state, artifact_list, model):
        return (None, [{"role": "user", "content": "compiled"}])

    monkeypatch.setattr(resp, "_compile_and_render", _fake_compile)
    llm = _FakeLLM(
        ["The temperature in Tokyo is 28.8 degrees Celsius."],
        failures=[False, True],
    )
    result = await resp.response_node(_state("p2a-e2e-8", "What is the weather in Tokyo?"), llm=llm, model="m")
    assert result.get("final_response") == "The temperature in Tokyo is 28.8 degrees Celsius."


def test_entailment_prompt_structural_no_domains():
    """The verifier prompt must be structural — artifact payloads are the
    evidence, NO domain lists, NO hardcoded capabilities."""
    import inspect

    from nexus.agent.nodes.response import _claim_entailment_supported

    src = inspect.getsource(_claim_entailment_supported)
    for domain_word in ("weather", "tokyo", "city_weather", "celsius", "population"):
        assert domain_word.lower() not in src.lower(), (
            f"entailment verifier must stay structural, found '{domain_word}'"
        )
