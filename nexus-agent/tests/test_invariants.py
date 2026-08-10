"""Invariant ledger (docs/invariants.md) — P0-A fail-closed gates.

Each invariant has one test class. Statuses:
  I1  GREEN (P0-A)   no unresolved RESOLVE crosses compiler -> executor
  I2  GREEN (P0-A)   no unresolved placeholder reaches a tool
  I3  GREEN (P0-A)   executable intent + empty plan + no artifacts != knowledge answer
  I4  GREEN (P0-B/B3) per-intent coverage evidence (engine-score alignment)
  I5  GREEN (P0-D)   durable operation identity
  I6  GREEN (P0-D)   terminal checkpoint cannot silently resume
  I7  GREEN (P1-A)   cache scope enforced before lookup
  I8  GREEN (P0-C)   approval bound to the exact approved operation
  I9  PARTIAL (P0-A) fail-closed prompt resolution; full boundary in P0-B/P2
  I10 GREEN (P2-B)   reproducible identity/versions persisted
  I11 GREEN (P0-D/P1-A) invalid plans cannot be cached or executed
  I12 GREEN (P1-A)   non-idempotent never auto-retried across uncertainty
  I13 GREEN (P2F)    semantic cache eligibility (validator verdict gates persistence)

Deterministic — no live server, no LLM, no DB.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from nexus.compiler.codegen import Compiler, CompilerError
from nexus.compiler.ir_models import LogicalNode, LogicalWorkflow

_SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "nexus"


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

    def model_dump(self) -> dict:
        return {}


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


# ---------------------------------------------------------------------------
# I1 — no unresolved RESOLVE(...) crosses the compiler -> executor boundary
# ---------------------------------------------------------------------------


class TestInvariantI1ResolveFailClosed:
    def test_unknown_capability_raises_compiler_error(self, monkeypatch):
        _fake_gc(monkeypatch)
        workflow = LogicalWorkflow(
            version="1.0",
            nodes=[
                LogicalNode(
                    op="get_current_weather",
                    ref="StepA",
                    inputs={"latitude": 'RESOLVE("no_such_capability", "k", "v")'},
                    depends_on=[],
                ),
            ],
            collections={},
        )
        compiler = Compiler(_FakeResolver())
        with pytest.raises(CompilerError, match="no_such_capability"):
            asyncio.run(compiler._synthesize_resolve_producers(workflow))

    def test_no_resolvable_endpoint_raises_compiler_error(self, monkeypatch):
        _fake_gc(monkeypatch)
        workflow = LogicalWorkflow(
            version="1.0",
            nodes=[
                LogicalNode(
                    op="get_current_weather",
                    ref="StepA",
                    inputs={"latitude": 'RESOLVE("unresolvable_cap", "k", "v")'},
                    depends_on=[],
                ),
            ],
            collections={},
        )
        compiler = Compiler(_FakeResolver())
        with pytest.raises(CompilerError):
            asyncio.run(compiler._synthesize_resolve_producers(workflow))

    def test_unsupported_chain_form_raises_compiler_error(self, monkeypatch):
        _fake_gc(monkeypatch)
        workflow = LogicalWorkflow(
            version="1.0",
            nodes=[
                LogicalNode(
                    op="get_current_weather",
                    ref="StepA",
                    inputs={"latitude": "{{legacy_ref}}"},
                    depends_on=[],
                ),
            ],
            collections={},
        )
        compiler = Compiler(_FakeResolver())
        with pytest.raises(CompilerError, match="unsupported chain expression"):
            asyncio.run(compiler._synthesize_resolve_producers(workflow))

    def test_resolvable_resolve_still_synthesizes(self, monkeypatch):
        """The P0-A change must not regress the happy path (mirrors
        test_codegen_resolve)."""
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
        assert "geocode_location" in {n.op for n in synthesized.nodes}
        weather = next(n for n in synthesized.nodes if n.op == "get_current_weather")
        assert weather.inputs["latitude"].startswith("${StepWeather_producer_")


# ---------------------------------------------------------------------------
# I2 — no unresolved placeholder reaches a tool (never None, never raw string)
# ---------------------------------------------------------------------------


class TestInvariantI2PlaceholderFailClosed:
    def test_unresolved_whole_string_placeholder_raises(self):
        from nexus.agent.executors.concurrent_executor import _resolve_placeholders
        from nexus.errors import PlaceholderResolutionError

        with pytest.raises(PlaceholderResolutionError):
            _resolve_placeholders(
                {"city": "${StepA.result.name}"},
                {},
                {"StepA": "task_missing"},
            )

    def test_unresolved_inline_placeholder_raises(self):
        from nexus.agent.executors.concurrent_executor import _resolve_placeholders
        from nexus.errors import PlaceholderResolutionError

        with pytest.raises(PlaceholderResolutionError):
            _resolve_placeholders(
                {"url": "https://example.com/${StepA.result.id}"},
                {},
                {"StepA": "task_missing"},
            )

    def test_missing_field_on_successful_dependency_raises(self):
        from nexus.agent.executors.concurrent_executor import _resolve_placeholders
        from nexus.errors import PlaceholderResolutionError

        with pytest.raises(PlaceholderResolutionError):
            _resolve_placeholders(
                {"city": "${StepA.result.nonexistent_field}"},
                {"task_1": {"name": "Tokyo"}},
                {"StepA": "task_1"},
            )

    def test_resolvable_placeholder_still_resolves(self):
        from nexus.agent.executors.concurrent_executor import _resolve_placeholders

        resolved = _resolve_placeholders(
            {"city": "${StepA.result.name}", "plain": "static"},
            {"task_1": {"name": "Tokyo"}},
            {"StepA": "task_1"},
        )
        assert resolved["city"] == "Tokyo"
        assert resolved["plain"] == "static"

    def test_failed_dependency_propagates_typed_error(self):
        from nexus.agent.executors.concurrent_executor import _resolve_placeholders
        from nexus.errors import PlaceholderResolutionError

        with pytest.raises(PlaceholderResolutionError):
            _resolve_placeholders(
                {"city": "${StepA.result.name}"},
                {"task_1": None},  # dependency task failed -> no result data
                {"StepA": "task_1"},
            )


# ---------------------------------------------------------------------------
# I3 — executable intent + empty plan + no artifacts != knowledge answer
# ---------------------------------------------------------------------------


class _FakeLLM:
    def __init__(self, content: str = "Tokyo is warm and sunny.") -> None:
        self._content = content

    async def complete(self, model=None, messages=None, **kwargs):
        class _R:
            content = self._content
            failed = False

        return _R()


class TestInvariantI3EmptyPlanNotSuccess:
    @pytest.fixture(autouse=True)
    def _reset_artifact_graph(self):
        import nexus.artifacts.graph as _ag

        _ag._GRAPHS.pop("sid-i3-test", None)
        yield
        _ag._GRAPHS.pop("sid-i3-test", None)

    def _base_state(self, query_type: str) -> dict:
        return {
            "session_id": "sid-i3-test",
            "messages": [{"role": "user", "content": "get weather in Tokyo"}],
            "_query_type": query_type,
            "_logical_workflow": {"version": "1.0", "nodes": [], "collections": {}},
            "_preferred_tools": [],
            "_plan_validator_report": None,
            "errors": [],
            "final_response": None,
            "response_type": "",
        }

    def test_action_intent_empty_plan_returns_not_success(self):
        from nexus.agent.nodes.response import response_node

        result = asyncio.run(
            response_node(self._base_state("action"), llm=_FakeLLM(), model="m")
        )
        assert result["response_type"] == "error", (
            "an action request with no plan must not be answered from knowledge"
        )
        assert "couldn't complete" in result["final_response"]

    def test_workflow_intent_empty_plan_returns_not_success(self):
        from nexus.agent.nodes.response import response_node

        result = asyncio.run(
            response_node(self._base_state("workflow"), llm=_FakeLLM(), model="m")
        )
        assert result["response_type"] == "error"

    def test_detected_executable_units_block_knowledge_answer(self):
        from nexus.agent.nodes.response import response_node

        state = self._base_state("information")
        state["_plan_validator_report"] = {
            "metrics": {"detected_executable": 2, "intent_coverage": 0.5},
        }
        result = asyncio.run(response_node(state, llm=_FakeLLM(), model="m"))
        assert result["response_type"] == "error"

    def test_conversation_intent_still_uses_chat_path(self):
        from nexus.agent.nodes.response import response_node

        state = self._base_state("conversation")
        result = asyncio.run(response_node(state, llm=_FakeLLM(), model="m"))
        assert result["response_type"] == "conversational"
        assert result["final_response"] == "Tokyo is warm and sunny."


# ---------------------------------------------------------------------------
# I9 (P0-A portion) — fail-closed prompt resolution
# ---------------------------------------------------------------------------


class TestInvariantI9PromptResolutionFailClosed:
    def test_missing_prompt_version_raises_typed_error(self):
        from nexus.agent.prompts.manager import PromptManager, PromptVersionError

        pm = PromptManager()
        pm.register("p", "template {x}", version="1.0")
        with pytest.raises(PromptVersionError):
            pm.render("p", "9.9", x="1")
        with pytest.raises(PromptVersionError):
            pm.get("missing_prompt")

    def test_all_rendered_prompt_versions_are_registered(self):
        """Every ``prompt_manager.render(...)``/``_pm.render(...)`` call site
        in src must reference a REGISTERED version — drift can never
        silently degrade a prompt again."""
        from nexus.agent.prompts import prompt_manager

        pattern = re.compile(
            r'(?:prompt_manager|_pm)\.render\(\s*"([a-z_]+)"'
            r'(?:\s*,\s*"([\d.]+)")?'
            r'(?:\s*,\s*version="([\d.]+)")?'
        )
        unregistered: list[tuple[str, str, str]] = []
        for py in _SRC_ROOT.rglob("*.py"):
            if "__pycache__" in str(py):
                continue
            text = py.read_text(encoding="utf-8")
            for m in pattern.finditer(text):
                name = m.group(1)
                version = m.group(2) or m.group(3)
                if version is None:
                    continue  # unversioned render -> highest registered (fine)
                if version not in prompt_manager.list_versions(name):
                    unregistered.append((str(py.relative_to(_SRC_ROOT)), name, version))
        assert not unregistered, f"unregistered prompt versions: {unregistered}"


# ---------------------------------------------------------------------------
# Future-stage invariants — explicitly PENDING, never silently dropped
# ---------------------------------------------------------------------------


class TestInvariantsPending:
    def test_i4_per_intent_coverage_evidence(self):
        """I4 (P0-B): every executable intent has explicit coverage evidence.

        Enforced in test_planner_p0b.py::TestB2IntentCoverageEvidence; this
        stub keeps the ledger's I4 slot visible with its true status."""
        pytest.skip("COVERED BY test_planner_p0b.py::TestB2IntentCoverageEvidence")

    def test_i5_durable_operation_identity(self):
        """I5 (P0-D/D1): covered by tests/test_idempotency_p0d.py — durable
        operation identity; attempt_id never participates in dedup."""
        pytest.skip("COVERED BY test_idempotency_p0d.py")

    def test_i6_terminal_checkpoint_cannot_resume(self):
        """I6 (P0-D/D2): covered by tests/test_terminal_checkpoint_p0d.py —
        terminal checkpoints never silently resume."""
        pytest.skip("COVERED BY test_terminal_checkpoint_p0d.py")

    def test_i7_cache_scope_enforced_before_lookup(self):
        pytest.skip("COVERED BY test_cache_scope_p1a.py")

    def test_i8_approval_bound_to_exact_operation(self):
        """I8 (P0-C): covered by tests/test_approval_p0c.py — the approval
        hash binds the grant to the exact operation."""
        pytest.skip("COVERED BY test_approval_p0c.py")

    def test_i10_reproducible_identity_persisted(self):
        """I10 (P2-B): covered by tests/test_reproducibility_p2b.py — the
        identity chain + fingerprints + plan refs reach the persisted
        outcome (three-way dataclass/model/migration parity)."""
        pytest.skip("COVERED BY test_reproducibility_p2b.py")

    def test_i11_invalid_plans_never_cached_or_executed(self):
        """I11 (P0-D/D0): covered by
        tests/test_plan_cache_p0d.py — the F4 cache-poisoning class."""
        pytest.skip("COVERED BY test_plan_cache_p0d.py")

    def test_i12_non_idempotent_never_auto_retried(self):
        """I12 (P1-A/A0): covered by tests/test_retry_semantics_p1a.py —
        the F7 discovery (non-idempotent transient retry on 500)."""
        pytest.skip("COVERED BY test_retry_semantics_p1a.py")

    def test_i13_semantic_cache_eligibility(self):
        """I13 (P2F): covered by tests/test_cache_semantic_p2f.py — a plan
        persists in the parse cache only under the full semantic
        eligibility contract; REFINE/ABORT/partial plans are removed."""
        pytest.skip("COVERED BY test_cache_semantic_p2f.py")
