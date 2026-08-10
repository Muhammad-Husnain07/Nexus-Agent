"""P2-B REPRODUCIBILITY gate — "exactly what produced this answer?"

The invocation outcome must persist the full evidence chain as REFERENCES
(never duplicated blobs), with hard parity contracts so the pre-P2-B
failure mode can never return: a field present in the outcome dataclass
but silently dropped at INSERT time.

Under test:

1. EVIDENCE ASSEMBLY — from_state builds every identity/contract/planner
   field from AgentState (request_id, agent_run_id, temperature, seed,
   architecture/registry fingerprints, prompt fingerprints, intent
   coverage summary, logical refs, attempt identity references).
2. REFERENCES NOT DUPLICATION — the logical graph / compiled plan are
   persisted as stable SHA256 refs; the full objects are NOT in the row.
   Ref stability: identical state → identical refs; drifted state →
       different refs (a plan change is always attributable).
3. INSERT PARITY — every dataclass field lands in the INSERT parameters;
   every DB model column is named in the INSERT; the dataclass/model/
       migration column sets agree (three-way contract).
4. IDENTITY ROUND-TRIP — request_id/agent_run_id survive from_state →
   parameters (the HTTP request is traceable to the persisted row).
"""

from __future__ import annotations

import dataclasses
import re

from nexus.observability.outcomes import (
    OUTCOME_VERSION,
    InvocationOutcome,
    _build_insert,
    _canonical_ref,
)


class _FakeResult:
    def __init__(self, tool: str, status: str, exec_key: str):
        self.tool_name = tool
        self.status = status
        self.execution_key = exec_key


def _state(**overrides) -> dict:
    state: dict = {
        "session_id": "sess-1",
        "errors": [],
        "_invocation_id": "run-abc-123",
        "tool_results": [],
        "_cost_breakdown": {"finalize": 0.001},
        "total_cost_usd": 0.001,
        "_total_tokens": 100,
        "_plan_validator_report": {
            "valid": True,
            "metrics": {
                "detected_intents": 2,
                "intent_confidence": 0.9,
                "detected_executable": 2,
                "served_intents": 2,
                "dropped_intents": 0,
                "intent_coverage": 1.0,
                "extraneous_operation_rate": 0.0,
                "intent_coverage_evidence": [
                    {"unit": "weather", "chosen": "get_current_weather", "served": True},
                    {"unit": "population", "chosen": "get_country_population", "served": True},
                ],
            },
        },
        "_logical_workflow": {
            "nodes": [
                {"id": "n1", "op": "get_current_weather", "params": {"city": "Tokyo"}},
                {"id": "n2", "op": "get_country_population", "params": {"country": "Japan"}},
            ],
        },
        "_execution_graph": {
            "waves": [
                [
                    {"id": "n1", "tool": "get_current_weather", "execution_key": "ek1"},
                ],
            ],
        },
    }
    state.update(overrides)
    return state


# ============================================================================
# 1. EVIDENCE ASSEMBLY
# ============================================================================


def test_evidence_identity_fields(monkeypatch):
    monkeypatch.setattr(
        "nexus.compiler.cache._registry_fingerprint", lambda: "reg-fp-1"
    )
    outcome = InvocationOutcome.from_state(
        _state(), 1234, request_id="req-xyz-42"
    )
    assert outcome.request_id == "req-xyz-42"
    assert outcome.agent_run_id == "run-abc-123"
    assert outcome.session_id == "sess-1"
    assert outcome.temperature is not None
    assert outcome.seed is None  # no seed configured — recorded for parity
    assert outcome.registry_fingerprint == "reg-fp-1"
    assert outcome.architecture_fingerprint  # ADR 0008 manifest hash


def test_evidence_prompt_fingerprints(monkeypatch):
    monkeypatch.setattr(
        "nexus.compiler.cache._registry_fingerprint", lambda: "reg-fp-1"
    )
    outcome = InvocationOutcome.from_state(_state(), 1)
    repro = outcome.reproducibility
    assert repro["model"] == outcome.model
    assert repro["architecture_fingerprint"] == outcome.architecture_fingerprint
    assert repro["registry_fingerprint"] == "reg-fp-1"
    assert set(repro["prompt_versions"]) == {"router", "logical_planner", "finalize"}
    # P1-B.2 component content fingerprints — content hash, not just version
    assert set(repro["prompt_fingerprints"]) >= {
        "router", "logical_planner", "finalize"
    }
    for name, fp in repro["prompt_fingerprints"].items():
        assert isinstance(fp, str), name
        assert len(fp) == 16, name


def test_evidence_planner_and_intent_coverage(monkeypatch):
    monkeypatch.setattr(
        "nexus.compiler.cache._registry_fingerprint", lambda: "reg-fp-1"
    )
    outcome = InvocationOutcome.from_state(_state(), 1)
    # full validator telemetry (incl. per-intent evidence) in planner_metrics
    assert outcome.planner_metrics["intent_coverage"] == 1.0
    assert outcome.planner_metrics["intent_coverage_evidence"][0]["unit"] == "weather"
    # compact aggregate summary in intent_coverage (no evidence duplication)
    assert outcome.intent_coverage["served_intents"] == 2
    assert outcome.intent_coverage["dropped_intents"] == 0
    assert "intent_coverage_evidence" not in outcome.intent_coverage


def test_evidence_attempt_identities():
    state = _state(
        tool_results=[
            {"tool_name": "get_current_weather", "status": "success", "execution_key": "ek-weather-1"},
            {"tool_name": "get_country_population", "status": "error", "execution_key": "ek-pop-2"},
        ]
    )
    outcome = InvocationOutcome.from_state(state, 1)
    assert outcome.attempts
    keys = list(outcome.attempts)
    assert any(k.startswith("get_current_weather:") for k in keys)
    assert any(k.startswith("get_country_population:") for k in keys)
    entry = outcome.attempts[keys[0]]
    # references only: execution-key identity + status, never result payloads
    assert set(entry) == {"execution_key", "status"}
    assert "data" not in entry


def test_from_state_tolerates_bare_state():
    outcome = InvocationOutcome.from_state({}, 1)
    assert outcome.session_id == ""
    assert outcome.model
    assert outcome.intent_coverage == {}
    assert outcome.planner_metrics == {}
    assert outcome.attempts == {}


# ============================================================================
# 2. REFERENCES NOT DUPLICATION + REF STABILITY
# ============================================================================


def test_logical_refs_are_hashes_not_blobs(monkeypatch):
    monkeypatch.setattr(
        "nexus.compiler.cache._registry_fingerprint", lambda: "reg-fp-1"
    )
    outcome = InvocationOutcome.from_state(_state(), 1)
    assert re.fullmatch(r"[0-9a-f]{64}", outcome.logical_intent_graph_ref)
    assert re.fullmatch(r"[0-9a-f]{64}", outcome.logical_plan_ref)
    data = outcome.to_dict()
    # the full logical workflow / execution graph are NOT duplicated —
    # only their reference hashes are persisted
    assert "_logical_workflow" not in data
    assert "_execution_graph" not in data
    assert all(len(v) <= 64 for v in (data["logical_intent_graph_ref"], data["logical_plan_ref"]))


def test_logical_refs_stable_for_identical_state():
    a = InvocationOutcome.from_state(_state(), 1)
    b = InvocationOutcome.from_state(_state(), 2)
    assert a.logical_intent_graph_ref == b.logical_intent_graph_ref
    assert a.logical_plan_ref == b.logical_plan_ref


def test_logical_refs_detect_plan_drift():
    """A drifted plan must produce a different reference — the attribution
    of an answer to a plan can never silently go stale."""
    base = _state()
    drifted = _state()
    drifted["_execution_graph"]["waves"][0].append(
        {"id": "n3", "tool": "get_news", "execution_key": "ek3"}
    )
    a = InvocationOutcome.from_state(base, 1)
    b = InvocationOutcome.from_state(drifted, 1)
    assert a.logical_plan_ref != b.logical_plan_ref
    assert a.logical_intent_graph_ref == b.logical_intent_graph_ref  # intents unchanged


def test_attempt_identities_stable_across_invocations():
    state = _state(
        tool_results=[{"tool_name": "w", "status": "success", "execution_key": "ek-1"}]
    )
    a = InvocationOutcome.from_state(state, 1)
    b = InvocationOutcome.from_state(state, 2)
    assert a.attempts == b.attempts


# ============================================================================
# 3. INSERT PARITY — the dataclass/model/migration three-way contract
# ============================================================================


def _outcome_data() -> dict:
    return InvocationOutcome.from_state(_state(), 5, request_id="req-1").to_dict()


def test_insert_parameters_cover_every_dataclass_field():
    _, params = _build_insert(_outcome_data())
    dataclass_fields = {f.name for f in dataclasses.fields(InvocationOutcome)}
    assert params.keys() - {"id", "outcome_version"} == dataclass_fields - {"created_at"}, (
        "every outcome field must reach the INSERT parameters "
        "(id/outcome_version are generated, created_at is server-side) — "
        "a silently dropped field is a bug"
    )


def test_insert_parameters_round_trip_identity():
    _, params = _build_insert(_outcome_data())
    assert params["request_id"] == "req-1"
    assert params["agent_run_id"] == "run-abc-123"
    assert params["temperature"] is not None
    assert params["seed"] is None
    assert params["registry_fingerprint"]
    assert params["logical_intent_graph_ref"]
    assert params["logical_plan_ref"]
    assert "intent_coverage" in params
    assert "planner_metrics" in params
    assert "reproducibility" in params
    assert "attempts" in params
    assert params["outcome_version"] == OUTCOME_VERSION


def test_insert_sql_names_every_model_column():
    sql, _ = _build_insert(_outcome_data())
    model_columns = _model_columns()
    # created_at is server-defaulted; id is generated — the INSERT covers
    # every other column (parity: the row stores ALL evidence).
    insert_columns = model_columns - {"created_at", "id"}
    for col in insert_columns:
        assert re.search(rf"\b{col}\b", sql), f"INSERT missing column {col}"


def test_model_and_migration_column_parity():
    """The SQLAlchemy model and the alembic migration must agree — a column
    added on one side and forgotten on the other breaks persistence. The
    migration adds exactly the P2-B set; the model must contain all of it."""
    model_cols = _model_columns()
    migration_cols = _migration_columns()
    assert migration_cols == _P2B_COLUMNS, (
        f"migration drift: unexpected={migration_cols - _P2B_COLUMNS} "
        f"missing={_P2B_COLUMNS - migration_cols}"
    )
    assert migration_cols <= model_cols, (
        f"model/migration drift — migration-only columns missing from the "
        f"model: {migration_cols - model_cols}"
    )


# the exact P2-B column set added by the f1a2b3c4d5e6 migration
_P2B_COLUMNS = {
    "architecture_fingerprint",
    "request_id",
    "agent_run_id",
    "temperature",
    "seed",
    "registry_fingerprint",
    "planner_metrics",
    "intent_coverage",
    "reproducibility",
    "logical_intent_graph_ref",
    "logical_plan_ref",
    "attempts",
}


def _model_columns() -> set[str]:
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "src" / "nexus" / "db" / "models" / "invocation_outcome.py"
    text = src.read_text(encoding="utf-8")
    return set(re.findall(r"^\s{4}(\w+): Mapped", text, re.MULTILINE))


def _migration_columns() -> set[str]:
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent
        / "alembic" / "versions" / "f1a2b3c4d5e6_p2b_reproducibility.py"
    )
    text = src.read_text(encoding="utf-8")
    block = text.split("_ADDED_COLUMNS = (", 1)[1].split("\n)\n", 1)[0]
    return set(re.findall(r"\('(\w+)',", block))


def test_canonical_ref_deterministic_and_drift_sensitive():
    obj = {"nodes": [{"id": "n1", "op": "x"}], "meta": {"order": [1, 2]}}
    assert _canonical_ref(obj) == _canonical_ref(obj)
    drifted = {"nodes": [{"id": "n1", "op": "y"}], "meta": {"order": [1, 2]}}
    assert _canonical_ref(obj) != _canonical_ref(drifted)
    # key order must not change the reference
    assert _canonical_ref({"a": 1, "b": 2}) == _canonical_ref({"b": 2, "a": 1})


def test_canonical_ref_deep_key_order_irrelevant():
    """Nested dict key reordering must not change the reference."""
    a = {"graph": {"waves": [{"id": "n1", "tool": "t", "params": {"x": 1, "y": 2}}]}}
    b = {"graph": {"waves": [{"params": {"y": 2, "x": 1}, "tool": "t", "id": "n1"}]}}
    assert _canonical_ref(a) == _canonical_ref(b)


def test_canonical_ref_list_order_semantically_significant():
    """Operation/wave ordering IS meaningful in an execution graph — a
    reordered plan must produce a different reference (an answer is
    attributable to the exact plan shape, not an order-insensitive bag)."""
    a = {"waves": [[{"id": "n1"}, {"id": "n2"}]]}
    b = {"waves": [[{"id": "n2"}, {"id": "n1"}]]}
    assert _canonical_ref(a) != _canonical_ref(b)


def test_canonical_ref_none_vs_absent_defined():
    """None and absent are DISTINCT by definition: an explicitly-nulled
    field is semantically different from a field the planner never emitted."""
    assert _canonical_ref({"a": None}) != _canonical_ref({})
    assert _canonical_ref({"a": None}) != _canonical_ref({"a": 1})
    # and the identity is stable
    assert _canonical_ref({"a": None}) == _canonical_ref({"a": None})
    assert _canonical_ref({}) == _canonical_ref({})


def test_canonical_ref_numeric_literals_not_coerced():
    """Numeric LITERALS are not coerced (defined): 1 and 1.0 differ — a
    typed producer emits a consistent literal form, so attribution is
    literal-stable without silent normalization."""
    assert _canonical_ref({"n": 1}) != _canonical_ref({"n": 1.0})
    assert _canonical_ref({"n": 1}) == _canonical_ref({"n": 1})
    assert _canonical_ref({"n": 1.0}) == _canonical_ref({"n": 1.0})


# ============================================================================
# 4. INVARIANT LEDGER SLOT (I10)
# ============================================================================


def test_i10_reproducible_identity_persisted():
    """I10 (P2-B): the reproducible identity chain — request_id /
    agent_run_id / fingerprints / plan refs — is assembled from state and
    reaches the persistence parameters for EVERY outcome."""
    _, params = _build_insert(_outcome_data())
    assert params["request_id"] == "req-1"
    assert params["agent_run_id"] == "run-abc-123"
    assert params["registry_fingerprint"]
    assert params["logical_plan_ref"]
    assert params["architecture_fingerprint"]
