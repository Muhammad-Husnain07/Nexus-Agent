"""RecoveryManager — one deterministic decision point, four recovery strategies.

Every failure is classified once and routed to exactly one strategy:

- ``RETRY``     — transient failure (timeout / 5xx / connection) with budget
                  left → ReflectionNode sub-graph retry (never replans).
- ``SELF_HEAL`` — contract failure with fallback candidates → SelfHealingNode
                  (alternative endpoints).
- ``REPLAN``    — structural invalidity: capability unavailable with no
                  fallback, schema changed, execution-policy violation (budget
                  exceeded mid-run, or an approval denial that blocks a
                  required dependency of the remaining graph) → ReplanNode →
                  planner (bounded rounds).
- ``FAIL``      — rounds exhausted / unrecoverable → explicit failure.

Reflection becomes ONE recovery strategy (transient retry), not the recovery
layer itself. Deterministic, metadata-driven, no tool-name logic.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RecoveryAction(str, Enum):
    """The four recovery strategies."""

    RETRY = "retry"
    SELF_HEAL = "self_heal"
    REPLAN = "replan"
    FAIL = "fail"


class RecoveryDecision(BaseModel):
    """Typed decision output consumed by the graph routing function."""

    model_config = ConfigDict(frozen=True)

    action: RecoveryAction = Field(description="Selected strategy")
    reason: str = Field(default="", description="Why (debug/telemetry)")
    round: int = Field(default=0, description="Recovery attempt number")


class RecoveryManager:
    """Deterministic failure → strategy classifier."""

    def __init__(self, max_replan_rounds: int = 1) -> None:
        self.max_replan_rounds = max_replan_rounds

    def decide(
        self,
        failures: list[dict[str, Any]],
        *,
        replan_rounds: int = 0,
        transient_retries_left: int = 0,
        has_fallback_candidates: bool = False,
        approval_blocked: bool = False,
        budget_violated: bool = False,
        workflow_owned: bool = False,
    ) -> RecoveryDecision:
        """Classify failures into exactly one recovery action.

        Args:
            failures: Failed task results (``status``/``error`` classified).
            replan_rounds: Replan attempts already consumed.
            transient_retries_left: Reflection retry budget remaining.
            has_fallback_candidates: Any failed op has alternative endpoints.
            approval_blocked: A denied approval blocks a required dependency
                of the remaining graph (documented rule — a non-blocking
                denial never replans).
            budget_violated: Execution-time budget cap exceeded.
            workflow_owned: Execution belongs to an interactive workflow — the
                workflow node owns step-level recovery, so a generic replan
                against the full catalog (raw user message, no workflow
                context) is never the right action. REPLAN becomes FAIL.

        Returns:
            A frozen ``RecoveryDecision``.
        """
        if workflow_owned:
            return RecoveryDecision(
                action=RecoveryAction.FAIL,
                reason="workflow-owned execution: step recovery is managed by the workflow node",
                round=replan_rounds,
            )

        if replan_rounds >= self.max_replan_rounds:
            return RecoveryDecision(
                action=RecoveryAction.FAIL,
                reason=f"replan rounds exhausted ({replan_rounds}/{self.max_replan_rounds})",
                round=replan_rounds,
            )

        if not failures and not approval_blocked and not budget_violated:
            return RecoveryDecision(action=RecoveryAction.FAIL, reason="no failures to recover")

        # Hard structural invalidity takes priority over everything: the plan
        # itself is no longer executable.
        hard_structural = any(self._is_structural(f) for f in failures)
        if hard_structural or approval_blocked or budget_violated:
            return RecoveryDecision(
                action=RecoveryAction.REPLAN,
                reason=self._structural_reason(failures, approval_blocked, budget_violated),
                round=replan_rounds + 1,
            )

        # Contract failures are healable by an alternative endpoint when
        # candidates exist; otherwise the plan itself is invalid → replan.
        contract_failure = any(self._is_contract(f) for f in failures)
        if contract_failure and has_fallback_candidates:
            return RecoveryDecision(
                action=RecoveryAction.SELF_HEAL,
                reason="contract failure with fallback candidates",
                round=replan_rounds,
            )
        if contract_failure:
            return RecoveryDecision(
                action=RecoveryAction.REPLAN,
                reason="contract failure without fallback — replan required",
                round=replan_rounds + 1,
            )

        if transient_retries_left > 0:
            return RecoveryDecision(
                action=RecoveryAction.RETRY,
                reason=f"transient failure, {transient_retries_left} retries left",
                round=replan_rounds,
            )

        return RecoveryDecision(
            action=RecoveryAction.FAIL,
            reason="no recovery strategy applicable",
            round=replan_rounds,
        )

    # ------------------------------------------------------------------
    # Failure classification (deterministic, metadata-driven)
    # ------------------------------------------------------------------

    @staticmethod
    def _is_structural(failure: dict[str, Any]) -> bool:
        """HARD structural: no endpoint can save this plan.

        Transient (timeout/5xx/connection) and contract mismatches are NOT
        hard structural — contract failures may be healed by fallbacks.
        Classification uses the TYPED failure status only — never error-text
        pattern matching (no hardcoded pattern lists). Producers emit typed
        statuses: the executor returns ``unavailable`` for a tripped circuit
        breaker and ``tool_not_found`` when a task's tool is not registered.
        """
        status = str(failure.get("status", "")).lower()
        if status in ("timeout", "rate_limited"):
            return False
        if status == "uncertain":
            # CANCELLATION (P0): the call was interrupted mid-execution —
            # the provider may have accepted the side effect. NEVER retried,
            # NEVER replayed: the outcome is unknowable by design.
            return False
        if status.isdigit() and status.startswith("5"):
            return False
        if status in ("unavailable", "tool_not_found"):
            return True
        return False

    @staticmethod
    def _is_contract(failure: dict[str, Any]) -> bool:
        """Contract mismatch: the tool responded but the payload violates the
        declared output contract / business rules / schema. Typed status only:
        ``validation_error`` covers input and output schema violations (the
        executor emits it for both)."""
        status = str(failure.get("status", "")).lower()
        return status == "validation_error"

    @staticmethod
    def _structural_reason(
        failures: list[dict[str, Any]],
        approval_blocked: bool,
        budget_violated: bool,
    ) -> str:
        if approval_blocked:
            return "approval denied on a required dependency (documented rule)"
        if budget_violated:
            return "execution budget exceeded — cheaper plan required"
        details = [str(f.get("error", ""))[:80] for f in failures]
        return "structural failure: " + "; ".join(details[:3])
