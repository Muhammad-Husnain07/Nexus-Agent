"""Invocation outcome tracking — costs, latency, success/failure, and the
P2-B reproducibility evidence needed to answer "exactly what produced this
answer?".

Identity chain anchors persisted here (references, not duplication):

    request_id → agent_run_id (_invocation_id) → operation (execution_key refs)
                    → attempt identities (execution_keys are stable across
                      retries; the retry indices live in the durable
                      completed_executions/execution_events ledger — P2-C
                      wires the full chain)

Evidence persisted per outcome:

    request_id / agent_run_id / session_id     identities
    model / temperature / seed                 LLM configuration
    architecture_fingerprint                   ADR 0008 manifest
    registry_fingerprint                       catalog/registry contract (P1-B)
    prompt_versions + prompt_fingerprints      P1-B.2 component fingerprints
    planner_metrics                            full validator telemetry
    intent_coverage                            aggregate coverage summary
    logical_intent_graph_ref / logical_plan_ref
                                               canonical SHA256 REFERENCES to
                                               the logical workflow / compiled
                                               execution graph (the full objects
                                               live in the checkpoint — never
                                               duplicated into the outcome row)
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

from nexus.config.settings import get_settings

logger = structlog.get_logger("nexus.observability.outcomes")

OUTCOME_VERSION = 3

_INTENT_COVERAGE_KEYS = (
    "intent_coverage",
    "served_intents",
    "dropped_intents",
    "detected_executable",
    "unclassifiable_units",
    "detected_intents",
    "intent_confidence",
    "empty_plan",
)


def _canonical_ref(obj: Any) -> str:
    """Deterministic reference hash of an object (stable JSON canonical form).

    P2-B REFERENCE CONTRACT: the outcome persists a SHA256 reference to the
    logical/execution graph instead of duplicating the objects themselves —
    the full artifacts live in the checkpoint, retrievable by
    (session_id, agent_run_id).

    CANONICALIZATION SEMANTICS (defined, stable — reproducibility must not
    be falsely sensitive to serialization details):

    - dict key ORDER is irrelevant — keys are always sorted (``sort_keys``).
    - dict key PRESENCE is significant: ``{"a": None}`` differs from
      ``{}`` and from ``{"a": 1}`` — an explicitly-nulled field is
      semantically different from a field the producer never emitted, and
      both differ from a populated field. This is the DEFINED behavior.
    - LIST ORDER IS significant: lists serialize in order, so operation/
      wave ordering (semantically meaningful in an execution graph) changes
      the reference. Callers with order-INSENSITIVE collections must sort
      them before hashing (never rely on incidental emission order).
    - numeric LITERALS are not coerced: ``1`` and ``1.0`` produce different
      references (defined — no silent int/float normalization; a typed
      producer always emits a consistent literal form).
    - non-JSON objects fall back to ``str()`` deterministically (defined,
      lossy, but stable for the same object type + repr).

    Anything not covered here is considered undefined and must not be
    relied on for attribution.
    """
    try:
        payload = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        payload = str(obj)
    return hashlib.sha256(payload.encode()).hexdigest()


def _intent_coverage_summary(metrics: dict[str, Any]) -> dict[str, Any]:
    """The compact coverage summary (aggregates only).

    The full per-intent coverage EVIDENCE (unit text, candidates, chosen,
    served, aligned — see plan_validator_node metrics
    ``intent_coverage_evidence``) is persisted in ``planner_metrics``; this
    column carries the scalar summary to keep the row queryable without
    duplicating the evidence array.
    """
    return {k: metrics[k] for k in _INTENT_COVERAGE_KEYS if k in metrics}


def _attempt_identities(tool_results: list[Any]) -> dict[str, Any]:
    """Per-operation attempt identity REFERENCES from executed results.

    Each executed operation is identified by its STABLE idempotency/execution
    key (the same key across retries — the provider deduplicates on it).
    Attempt COUNT/retry indices are not re-derived here: they live in the
    durable ledger (completed_executions/execution_events), which the
    identity chain (P2-C) joins on (session_id, execution_key).
    """
    identities: dict[str, Any] = {}
    for r in tool_results or []:
        if not isinstance(r, dict):
            continue
        tool = str(r.get("tool_name") or r.get("tool") or "unknown")
        identities[f"{tool}:{r.get('execution_key', '')[:16]}"] = {
            "execution_key": r.get("execution_key", "")[:40],
            "status": r.get("status", ""),
        }
    return identities


@dataclass
class InvocationOutcome:
    """Record of a single agent invocation for analytics and debugging."""

    session_id: str
    model: str
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    latency_ms: int = 0
    success: bool = False
    tool_count: int = 0
    tool_error_count: int = 0
    error_message: str | None = None
    cost_breakdown: dict[str, Any] = None
    created_at: str = ""
    architecture_fingerprint: str = ""
    planner_metrics: dict[str, Any] = None
    reproducibility: dict[str, Any] = None
    # P2-B: reproducibility evidence + identity chain anchors
    request_id: str | None = None
    agent_run_id: str | None = None
    temperature: float | None = None
    seed: int | None = None
    registry_fingerprint: str = ""
    intent_coverage: dict[str, Any] = None
    logical_intent_graph_ref: str = ""
    logical_plan_ref: str = ""
    attempts: dict[str, Any] = None

    def __post_init__(self):
        if self.cost_breakdown is None:
            self.cost_breakdown = {}
        if self.planner_metrics is None:
            self.planner_metrics = {}
        if self.reproducibility is None:
            self.reproducibility = {}
        if self.intent_coverage is None:
            self.intent_coverage = {}
        if self.attempts is None:
            self.attempts = {}
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_state(
        state: dict[str, Any],
        latency_ms: int,
        error_message: str | None = None,
        request_id: str | None = None,
    ) -> InvocationOutcome:
        """Build an outcome record from AgentState (P2-B evidence assembly).

        Args:
            state: The final AgentState of the invocation.
            latency_ms: Wall-clock latency of the invocation.
            error_message: Terminal error message, if the invocation failed.
            request_id: The API request correlation id (RequestIDMiddleware).

        Returns:
            An InvocationOutcome with all reproducibility evidence attached.
        """
        settings = get_settings()
        model = settings.llm.default_model
        tool_results: list = state.get("tool_results", [])
        tool_count = len(tool_results)
        tool_errors = sum(1 for r in tool_results if r.get("status") != "success") if tool_results else 0
        cost_breakdown = state.get("_cost_breakdown", {})
        try:
            from nexus.agent.architecture import ArchitectureVersion  # noqa: PLC0415

            architecture_fingerprint = ArchitectureVersion.cache_fingerprint()
        except Exception:
            architecture_fingerprint = ""
        planner_metrics = {}
        try:
            _report = state.get("_plan_validator_report") or {}
            if isinstance(_report, dict):
                planner_metrics = _report.get("metrics") or {}
        except Exception:
            planner_metrics = {}
        # REGISTRY FINGERPRINT (P1-B contract): the catalog/registry fingerprint
        # — any registry change (new tool, edited template, provider update)
        # changes it, so a cached/derived artifact can never be attributed to
        # the wrong contract.
        registry_fingerprint = ""
        try:
            from nexus.compiler.cache import _registry_fingerprint as _reg_fp  # noqa: PLC0415

            registry_fingerprint = _reg_fp()
        except Exception:
            registry_fingerprint = ""
        # P2-B REPRODUCIBILITY: model identity + prompt fingerprints (P1-B.2
        # component content hashes — a prompt CONTENT change is captured even
        # when the version label is unchanged) + LLM configuration.
        reproducibility: dict[str, Any] = {
            "model": model,
            "temperature": settings.agent.finalize_temperature,
            "seed": None,  # no seed is configured — recorded for parity
        }
        try:
            from nexus.agent.architecture import ArchitectureVersion  # noqa: PLC0415
            from nexus.agent.prompts.manager import prompt_manager  # noqa: PLC0415

            reproducibility["architecture_fingerprint"] = ArchitectureVersion.cache_fingerprint()
            reproducibility["registry_fingerprint"] = registry_fingerprint
            reproducibility["prompt_versions"] = {}
            reproducibility["prompt_fingerprints"] = {}
            for name in ("router", "logical_planner", "finalize"):
                try:
                    tmpl = prompt_manager.get(name)
                    reproducibility["prompt_versions"][name] = getattr(tmpl, "version", "") or ""
                except Exception:
                    pass
            try:
                reproducibility["prompt_fingerprints"] = prompt_manager.fingerprints()
            except Exception as exc:
                logger.warning("outcome.prompt_fingerprints_failed", error=str(exc))
        except Exception as exc:
            logger.warning("outcome.reproducibility_failed", error=str(exc))

        return InvocationOutcome(
            session_id=state.get("session_id", ""),
            model=model,
            total_cost_usd=state.get("total_cost_usd", 0.0),
            total_tokens=state.get("_total_tokens", 0),
            latency_ms=latency_ms,
            success=error_message is None and not state.get("errors"),
            tool_count=tool_count,
            tool_error_count=tool_errors,
            error_message=error_message,
            cost_breakdown=cost_breakdown,
            architecture_fingerprint=architecture_fingerprint,
            planner_metrics=planner_metrics,
            reproducibility=reproducibility,
            request_id=request_id,
            agent_run_id=state.get("_invocation_id", ""),
            temperature=settings.agent.finalize_temperature,
            seed=None,
            registry_fingerprint=registry_fingerprint,
            intent_coverage=_intent_coverage_summary(planner_metrics),
            logical_intent_graph_ref=_canonical_ref(state.get("_logical_workflow")),
            logical_plan_ref=_canonical_ref(state.get("_execution_graph")),
            attempts=_attempt_identities(tool_results),
        )


def _build_insert(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The full INSERT statement + parameters for the outcome row.

    P2-B PARITY CONTRACT: EVERY reproducibility field of the outcome must
    appear in this INSERT — a field may never be present in the dataclass
    and silently dropped at persistence time (the pre-P2-B failure mode).
    The statement is built here so tests can assert the parity without a DB.
    """
    sql = (
        "INSERT INTO invocation_outcomes "
        "(id, session_id, model, total_cost_usd, total_tokens, latency_ms, "
        "success, tool_count, tool_error_count, "
        "error_message, cost_breakdown, outcome_version, "
        "architecture_fingerprint, "
        "request_id, agent_run_id, temperature, seed, "
        "registry_fingerprint, planner_metrics, intent_coverage, "
        "reproducibility, logical_intent_graph_ref, logical_plan_ref, attempts) "
        "VALUES (:id, :session_id, :model, :total_cost_usd, :total_tokens, "
        ":latency_ms, :success, :tool_count, :tool_error_count, "
        ":error_message, CAST(:cost_breakdown AS JSONB), :outcome_version, "
        ":architecture_fingerprint, "
        ":request_id, :agent_run_id, :temperature, :seed, "
        ":registry_fingerprint, CAST(:planner_metrics AS JSONB), "
        "CAST(:intent_coverage AS JSONB), CAST(:reproducibility AS JSONB), "
        ":logical_intent_graph_ref, :logical_plan_ref, CAST(:attempts AS JSONB))"
    )
    params: dict[str, Any] = {
        "id": uuid.uuid4(),
        "session_id": data["session_id"],
        "model": data["model"],
        "total_cost_usd": data["total_cost_usd"],
        "total_tokens": data["total_tokens"],
        "latency_ms": data["latency_ms"],
        "success": data["success"],
        "tool_count": data["tool_count"],
        "tool_error_count": data["tool_error_count"],
        "error_message": data["error_message"],
        "cost_breakdown": json.dumps(data["cost_breakdown"]),
        "outcome_version": OUTCOME_VERSION,
        "architecture_fingerprint": data.get("architecture_fingerprint") or "",
        "request_id": data.get("request_id"),
        "agent_run_id": data.get("agent_run_id"),
        "temperature": data.get("temperature"),
        "seed": data.get("seed"),
        "registry_fingerprint": data.get("registry_fingerprint") or "",
        "planner_metrics": json.dumps(data.get("planner_metrics") or {}),
        "intent_coverage": json.dumps(data.get("intent_coverage") or {}),
        "reproducibility": json.dumps(data.get("reproducibility") or {}),
        "logical_intent_graph_ref": data.get("logical_intent_graph_ref") or "",
        "logical_plan_ref": data.get("logical_plan_ref") or "",
        "attempts": json.dumps(data.get("attempts") or {}),
    }
    return sql, params


async def persist_outcome(outcome: InvocationOutcome) -> None:
    """Persist an invocation outcome to PostgreSQL. Fire-and-forget."""
    try:
        from sqlalchemy import text  # noqa: PLC0415

        from nexus.db.base import async_session  # noqa: PLC0415

        data = outcome.to_dict()
        sql, params = _build_insert(data)
        async with async_session() as session:
            await session.execute(text(sql), params)
            await session.commit()
        logger.info("outcome.persisted", session_id=outcome.session_id)
    except Exception as exc:
        logger.warning("outcome.persist_failed", error=str(exc))
