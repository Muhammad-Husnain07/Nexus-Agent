"""PlanValidatorNode — deterministic safety layer between planner and compiler.

Checks the LogicalWorkflow BEFORE compilation (runtime contract §6): undefined
ops, cycles, missing inputs, budget, and policy/permission violations. Zero
LLM calls; every violation is recorded in a typed ``PlanValidatorReport`` with
severity + suggested action. The graph routes on the report: valid →
Compiler, structural → RequirementCollector, refinable → PlanCritic.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field

from nexus.context import global_context as _gc_mod

logger = structlog.get_logger("nexus.agent.nodes.plan_validator")


class ViolationSeverity(str, Enum):
    """Severity ladder — CRITICAL and ERROR block compilation."""

    CRITICAL = "critical"      # cannot compile (cycle, undefined op)
    ERROR = "error"            # must not execute (missing input, budget)
    WARNING = "warning"        # policy note (approval required, high risk)


class ViolationAction(str, Enum):
    """What the graph should do about the violation."""

    DROP_OP = "drop_op"                        # remove the offending node
    REQUIRE_MORE_INFO = "require_more_info"    # route to RequirementCollector
    REFINE = "refine"                          # route to PlanCritic (LLM refine)
    APPROVAL = "approval"                      # gate will handle (not blocking)
    PROCEED = "proceed"                        # informational only
    # P1-A: drop nodes whose required inputs have NO resolvable source
    # (binder-classified) and proceed — deterministic partial success on
    # multi-node plans WITHOUT a full-LLM replan (the wall-time class).
    DROP_AND_PROCEED = "drop_and_proceed"


class Violation(BaseModel):
    """One validated finding."""

    model_config = ConfigDict(frozen=True)

    code: str = Field(description="Stable violation code (machine-readable)")
    severity: ViolationSeverity = Field(description="Severity ladder position")
    action: ViolationAction = Field(description="Suggested graph action")
    node: str = Field(default="", description="Offending logical op / step ref")
    message: str = Field(description="Human-readable explanation")


class PlanValidatorReport(BaseModel):
    """Typed validator output consumed by the routing function."""

    model_config = ConfigDict(frozen=True)

    valid: bool = Field(description="True when the plan may compile")
    violations: tuple[Violation, ...] = Field(default_factory=tuple)
    errors: list[str] = Field(
        default_factory=list, description="Human-readable messages (no-guess contract)"
    )
    metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="Planner-quality metrics: intent_coverage, dropped_intents, "
        "extraneous_operation_rate, empty_plan (P4 telemetry)",
    )

    @property
    def action(self) -> ViolationAction:
        """Dominant action: worst severity wins.

        P1-A: DROP_AND_PROCEED wins when unresolvable-input drops are
        present — even alongside alignment/coverage (the reviewer's L5:
        weak alignment is evidence-only on a plan that also carries
        unresolvable inputs; REFINE would replan the whole DAG for a
        docker ``repository`` that does not exist — the mega-DAG wall-time
        class). A plan whose ONLY errors are alignment/coverage still
        REFINEs.
        """
        for v in self.violations:
            if v.severity == ViolationSeverity.CRITICAL:
                return v.action
        errors = [v for v in self.violations if v.severity == ViolationSeverity.ERROR]
        if errors:
            has_unresolvable = any(
                v.action == ViolationAction.DROP_AND_PROCEED for v in errors
            )
            if all(
                v.action in (
                    ViolationAction.DROP_AND_PROCEED,
                    ViolationAction.REFINE,
                ) for v in errors
            ) and has_unresolvable:
                # Mixed unresolvable-drop + refinement (alignment/coverage):
                # drop the unresolvable nodes and proceed — the refinement
                # classes are evidence-only on mega-DAGs where a single
                # missing input must not void 8 valid branches.
                return ViolationAction.DROP_AND_PROCEED
            if all(
                v.action == ViolationAction.DROP_AND_PROCEED for v in errors
            ):
                return ViolationAction.DROP_AND_PROCEED
            # Mixed verdict: a repair-worthy error outranks partial drops.
            for v in errors:
                if v.action != ViolationAction.DROP_AND_PROCEED:
                    return v.action
        for v in self.violations:
            if v.action != ViolationAction.PROCEED:
                return v.action
        return ViolationAction.PROCEED


class PlanValidatorNode:
    """Deterministic plan validation (stateless; injected readers)."""

    def __init__(self, budget_cap_usd: float | None = None) -> None:
        self.budget_cap_usd = budget_cap_usd

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        workflow = state.get("_logical_workflow") or {}
        nodes = workflow.get("nodes") or []
        prior_chain = _prior_executed_chain(state)
        user_query = _current_user_query(state)
        # B3 (engine-score alignment): gather the deterministic resolver's
        # per-unit SCORES for the SAME intent units validate() detects
        # (identical deterministic IntentDetector call). Units resolve to
        # ranked (capability, score) pairs — the validator's alignment
        # verdict is score-based, never a keyword proxy. Deterministic,
        # GC-only, bounded by the unit count.
        # P0-C: when a STRUCTURED intent graph exists, its GOALS are the
        # units — engine scores must be computed for those same goals or
        # the coverage check cannot see the second intent's candidates
        # (the K83 "find the address at the coordinate" goal).
        structured_intents = None
        try:
            _detected_state = state.get("_detected_intents")
            if isinstance(_detected_state, dict) and _detected_state.get("intents"):
                structured_intents = _detected_state
        except Exception:
            structured_intents = None
        engine_scores: dict[str, list[tuple[str, float]]] = {}
        try:
            from nexus.agent.planners.intent_detector import IntentDetector  # noqa: PLC0415

            if structured_intents is not None:
                _units_for_scores = [
                    str(i.get("goal") or "").strip()
                    for i in structured_intents.get("intents") or []
                    if isinstance(i, dict) and str(i.get("goal") or "").strip()
                ]
            else:
                _detected = IntentDetector().detect(user_query) if user_query else None
                _units_for_scores = (
                    [u.text for u in _detected.units] if _detected is not None else []
                )
            for _u in _units_for_scores:
                engine_scores[_u] = await _engine_ranked_for_unit(_u)
        except Exception as _esc:
            logger.warning("plan_validator.engine_scores_failed", error=str(_esc)[:150])
        # P0-D.1: the ALIGNMENT verdict must consume the SAME semantic
        # representation as the resolver — generic-suppressed engine scores.
        # A correct specialized pick is never rejected because the generic
        # fallback outscored it in raw terms (the D48/D49 class). The
        # filtered scores feed the alignment loop only; coverage keeps the
        # raw candidates (the planner must still SEE the generic exists).
        try:
            filtered_scores = {
                u: await _semantic_filter_engine(ranked, u)
                for u, ranked in (engine_scores or {}).items()
            }
        except Exception:
            filtered_scores = engine_scores
        report = self.validate(
            nodes,
            prior_chain=prior_chain,
            user_query=user_query,
            collections=workflow.get("collections") if isinstance(workflow, dict) else None,
            preferred_tools=state.get("_preferred_tools") or None,
            engine_scores=engine_scores,
            alignment_scores=filtered_scores,
            structured_intents=structured_intents,
            binding_report=state.get("_binding_report"),
        )
        # P0-B: surface the binder's provenance ledger on the report metrics
        # (BOUND/MISSING/AMBIGUOUS classification — the benchmark's
        # BINDING_FAILED class, never a bare "missing inputs" string).
        binding_report = state.get("_binding_report")
        if isinstance(binding_report, dict):
            missing = [m for m in (binding_report.get("missing") or []) if isinstance(m, dict)]
            metrics = dict(report.metrics)
            metrics["binding"] = {
                "bound_required_params": len(binding_report.get("bindings") or []),
                "missing_required_params": len(missing),
                "missing_states": {
                    m.get("parameter"): m.get("state") for m in missing
                },
            }
            errors = list(report.errors)
            for m in missing:
                if m.get("state") == "MISSING":
                    errors.append(
                        f"BINDING_FAILED: {m.get('node_id') or '?'} "
                        f"requires {m.get('parameter') or '?'} — "
                        f"{m.get('reason') or 'no resolvable source'}"
                    )
            report = PlanValidatorReport(
                valid=report.valid,
                violations=report.violations,
                errors=errors,
                metrics=metrics,
            )
        rounds = int(state.get("_plan_validator_rounds", 0) or 0)

        # Gate: PROCEED when the report is valid (no CRITICAL/ERROR).
        # capability_alignment (B3, engine-score based) BLOCKS only on
        # STRONG deterministic evidence (unique/dominant engine top vs a
        # different pick); ambiguous/weak evidence is evidence-only and
        # never blocks (the historical false-positive class: scenarios
        # 8/20/38/47 lived in weak-signal territory).
        # P2F SEMANTIC CACHE GATEKEEPER: the planner writes the cache BEFORE
        # this node, so a semantically invalid plan may already be stored
        # (or replayed from an old entry). Any verdict that is NOT
        # cache-eligible — REFINE, ABORT, require_more_info, or the
        # partial-execution PROCEED (coverage < 100%) — removes the entry:
        # a syntactically valid plan is not semantically safe to cache.
        if not _semantic_cache_eligible(report):
            await _remove_semantically_ineligible_plan(state, "validator_verdict")

        if report.valid:
            logger.info("plan_validator.passed", nodes=len(nodes))
            return {
                "_plan_validator_report": report.model_dump(mode="json"),
                "_plan_validator_action": "proceed",
                "_plan_validator_errors": [],
                "_plan_validator_rounds": rounds,
            }

        logger.warning(
            "plan_validator.rejected",
            violations=[v.code for v in report.violations],
            action=report.action.value,
        )

        if report.action == ViolationAction.REQUIRE_MORE_INFO:
            return {
                "_plan_validator_report": report.model_dump(mode="json"),
                "_plan_validator_action": "require_more_info",
                "_plan_validator_errors": report.errors,
                "_plan_validator_rounds": rounds,
            }

        # P1-A DROP_AND_PROCEED: nodes whose required inputs have NO
        # resolvable source (binder-classified) are physically removed and
        # the remaining plan proceeds — deterministic partial success, no
        # full-LLM replan (the large-DAG wall-time class: V134 burned
        # 50-90s per replan round for one unbound param on a 24-node plan).
        if report.action == ViolationAction.DROP_AND_PROCEED:
            _drop_ops = {
                str(v.node) for v in report.violations
                if v.action == ViolationAction.DROP_AND_PROCEED
            }
            _workflow = workflow if isinstance(workflow, dict) else {}
            _nodes = _workflow.get("nodes") or []
            _surviving = [
                n for n in _nodes
                if not (isinstance(n, dict) and str(n.get("op") or "") in _drop_ops)
            ]
            logger.warning(
                "plan_validator.drop_and_proceed",
                dropped=sorted(_drop_ops),
                surviving=len(_surviving),
            )
            _workflow["nodes"] = _surviving
            return {
                "_plan_validator_report": report.model_dump(mode="json"),
                "_plan_validator_action": "proceed",
                "_plan_validator_errors": [],
                "_plan_validator_rounds": rounds,
                # Errors ride the patch so the response reports the drop
                # honestly (never silent success — PARTIAL_SUCCESS).
                "errors": report.errors,
                "_logical_workflow": _workflow,
            }

        # Refinable defects (cycle / budget / undefined): bounded replan loop.
        # The loop consumes the INVOCATION ReasoningBudget's shared replan
        # counter (unified with compile retries + recovery replans — the
        # same failure can never trigger an identical replan indefinitely).
        try:
            from nexus.config.settings import get_settings

            max_rounds = get_settings().compiler.max_plan_validator_rounds
        except Exception:
            max_rounds = 2
        _budget = None
        _budget_ok = True
        try:
            from nexus.agent.budget import budget_from_state

            _budget = budget_from_state(state)
            _budget_ok = _budget.consume("replans")
        except Exception:
            _budget_ok = True
        if rounds >= max_rounds or not _budget_ok:
            logger.error("plan_validator.abort", errors=report.errors)
            # P4 policy: after bounded repair —
            #   empty_plan (executable query, nothing to run) → clarify
            #     (the correctness case: never answer from training).
            #   intent_coverage/extraneous (a partial plan exists) →
            #     PROCEED with the best-effort plan (principle 23: return
            #     partial results; the coverage signal rides the outcome).
            if any(v.code == "empty_plan" for v in report.violations):
                return {
                    "_plan_validator_report": report.model_dump(mode="json"),
                    "_plan_validator_action": "require_more_info",
                    "_plan_validator_errors": report.errors,
                    "_plan_validator_rounds": rounds,
                    "errors": report.errors,
                }
            if any(v.code == "missing_input" for v in report.violations):
                # After bounded repair the inputs are still absent — the
                # user must provide them (genuine clarification).
                return {
                    "_plan_validator_report": report.model_dump(mode="json"),
                    "_plan_validator_action": "require_more_info",
                    "_plan_validator_errors": report.errors,
                    "_plan_validator_rounds": rounds,
                    "errors": report.errors,
                }
            if any(
                v.code in ("intent_coverage", "extraneous_operation")
                for v in report.violations
            ):
                logger.warning(
                    "plan_validator.partial_execution",
                    errors=report.errors,
                )
                return {
                    "_plan_validator_report": report.model_dump(mode="json"),
                    "_plan_validator_action": "proceed",
                    "_plan_validator_errors": report.errors,
                    "_plan_validator_rounds": rounds,
                }
            return {
                "_plan_validator_report": report.model_dump(mode="json"),
                "_plan_validator_action": "abort",
                "_plan_validator_errors": report.errors,
                "_logical_workflow": None,
                "errors": report.errors,
            }
        return {
            "_plan_validator_report": report.model_dump(mode="json"),
            "_plan_validator_action": "refine",
            "_plan_validator_errors": report.errors,
            "_plan_validator_rounds": rounds + 1,
            "_invocation_budget": _budget.to_dict() if _budget is not None else {},
        }

    # ------------------------------------------------------------------
    # Pure validation core (side-effect free; testable with fakes)
    # ------------------------------------------------------------------

    def validate(
        self,
        nodes: list[dict[str, Any]],
        prior_chain: list[str] | None = None,
        user_query: str | None = None,
        collections: dict[str, Any] | None = None,
        preferred_tools: list[str] | None = None,
        engine_scores: dict[str, list[tuple[str, float]]] | None = None,
        alignment_scores: dict[str, list[tuple[str, float]]] | None = None,
        structured_intents: dict[str, Any] | None = None,
        binding_report: dict[str, Any] | None = None,
    ) -> PlanValidatorReport:
        violations: list[Violation] = []
        errors: list[str] = []
        metrics: dict[str, Any] = {}

        # INTENT DECOMPOSITION (P4, Tier-1 deterministic): detect the
        # current request's intent units BEFORE any structural check — the
        # empty-plan and coverage/traceability rules need them. P0-C: when
        # the planner's adaptive decomposition produced a STRUCTURED intent
        # graph (goals/entities/relationships — the K83 anaphoric chain),
        # the coverage check uses those intents instead of the clause split.
        detected = _detect_intents(user_query) if user_query else None
        if structured_intents is not None and structured_intents.get("intents"):
            detected = _structured_to_detected(structured_intents)
        if detected is not None and detected.units:
            metrics["detected_intents"] = len(detected.units)
            metrics["intent_confidence"] = round(detected.confidence, 2)

        if not nodes:
            if detected is not None and _has_executable_units(detected):
                # P4-2 EMPTY-PLAN POLICY: an executable request with an
                # empty plan must NOT fall through to the conversational
                # LLM (training-knowledge answers are unverified). Repair
                # (REFINE) with the units listed; the cap routes to
                # clarification.
                violations.append(Violation(
                    code="empty_plan",
                    severity=ViolationSeverity.ERROR,
                    action=ViolationAction.REFINE,
                    node="plan",
                    message=(
                        "detected executable intent units but the plan is "
                        f"empty: {_units_text(detected)}"
                    ),
                ))
                errors.append(
                    f"empty plan for executable request: {_units_text(detected)}"
                )
                metrics["empty_plan"] = True
                return PlanValidatorReport(
                    valid=False, violations=tuple(violations),
                    errors=errors, metrics=metrics,
                )
            return PlanValidatorReport(valid=True, violations=(), errors=[], metrics=metrics)

        valid_ops = _valid_op_names()

        # 1. Undefined ops (against the resolved catalog).
        for node in nodes:
            op = str(node.get("op") or "")
            if op and valid_ops and op not in valid_ops:
                violations.append(Violation(
                    code="undefined_op",
                    severity=ViolationSeverity.CRITICAL,
                    action=ViolationAction.DROP_OP,
                    node=op,
                    message=f"op '{op}' is not a resolved capability",
                ))
                errors.append(f"undefined capability: {op}")

        # 2. Cycles over depends_on refs (DFS before compile).
        cycle = _find_cycle(nodes)
        if cycle:
            path = " -> ".join(cycle)
            violations.append(Violation(
                code="cycle",
                severity=ViolationSeverity.CRITICAL,
                action=ViolationAction.REFINE,
                node=path,
                message=f"dependency cycle: {path}",
            ))
            errors.append("dependency cycle detected")

        # 2b. ITERATE_OVER RESOLVABILITY (F1/P0-B): a node declaring
        # ``iterate_over`` must reference a declared, non-empty collection
        # OR a runtime-produced placeholder (``${ref.result...}``). A map
        # over a phantom collection would silently fall back to a single
        # body execution at runtime (graph.py) and produce misleading
        # plan_created events — the planner must never emit it.
        for node in nodes:
            io_key = node.get("iterate_over")
            if not io_key or not isinstance(io_key, str):
                continue
            if io_key.startswith("${"):
                continue  # runtime-produced collection (producer chain)
            declared = (
                isinstance(collections, dict)
                and io_key in collections
                and isinstance(collections[io_key], list)
                and bool(collections[io_key])
            )
            if not declared:
                violations.append(Violation(
                    code="unresolved_iterate_over",
                    severity=ViolationSeverity.ERROR,
                    action=ViolationAction.REFINE,
                    node=str(node.get("op") or ""),
                    message=(
                        f"iterate_over '{io_key}' does not reference a "
                        "declared non-empty collection"
                    ),
                ))
                errors.append(
                    f"unresolved iterate_over: {io_key} on "
                    f"{node.get('op') or '?'}"
                )

        # 3. Missing required inputs (schema-driven; GC meta carries the
        # required-property list built from the tool's input_schema).
        # Empty/whitespace values are NOT provided — they would fail at
        # execution with a type error, so the plan is invalid as-is.
        # P1-A: when the P0-B binder already classified the missing param
        # as UNRESOLVABLE (no source after L1-L5), REFINE cannot help — the
        # whole-plan replan burns the wall-time budget on a large DAG for a
        # value that does not exist. DROP the node instead (explicit
        # partial success — the reviewer's state machine), but ONLY when
        # other executable nodes remain; a single-node plan still REFINEs.
        _binding_missing_params: set[str] = set()
        try:
            _bm = (binding_report or {}).get("missing") or []
            _binding_missing_params = {
                str(m.get("parameter") or "") for m in _bm
                if isinstance(m, dict) and m.get("clarification_required") is True
            }
        except Exception:
            _binding_missing_params = set()
        for node in nodes:
            op = str(node.get("op") or "")
            node_inputs = node.get("inputs") or {}
            if isinstance(node_inputs, dict):
                provided = {
                    k for k, v in node_inputs.items()
                    if not (isinstance(v, str) and not v.strip())
                }
            else:
                provided = set(node_inputs)
            missing = _missing_inputs(op, provided)
            if missing:
                _unbound = missing & _binding_missing_params
                _has_other_executable = any(
                    (n is not node) and str(n.get("op") or "").strip()
                    for n in nodes
                )
                if _unbound and _has_other_executable:
                    # P1-A DROP_AND_PROCEED for genuinely-missing values on
                    # multi-node plans: keep the valid branches, drop the
                    # unplannable node, report partial success — WITHOUT a
                    # full-LLM replan (the large-DAG wall-time class). The
                    # node is physically removed below in __call__.
                    violations.append(Violation(
                        code="missing_input_unresolvable",
                        severity=ViolationSeverity.ERROR,
                        action=ViolationAction.DROP_AND_PROCEED,
                        node=op,
                        message=(
                            f"{op} missing inputs with no resolvable source: "
                            f"{', '.join(sorted(_unbound))} — node dropped, "
                            "remaining plan proceeds"
                        ),
                    ))
                    errors.append(
                        f"{op} dropped (unresolvable inputs: {', '.join(sorted(_unbound))})"
                    )
                    continue
                violations.append(Violation(
                    code="missing_input",
                    severity=ViolationSeverity.ERROR,
                    action=ViolationAction.REFINE,
                    node=op,
                    message=f"{op} missing inputs: {', '.join(sorted(missing))}",
                ))
                errors.append(f"{op} missing inputs: {', '.join(sorted(missing))}")

        # 3b. Schema type violations: an input VALUE the tool's declared JSON
        # Schema type cannot ever accept (e.g. ``"temperature"`` for a
        # ``boolean`` param) would fail at execution with a validation error.
        # The deterministic validator drops the node pre-compile (explicit
        # failure — never a runtime surprise). Coercible values (numeric
        # strings for numbers, boolean-ish strings for booleans) and
        # unresolved placeholders (``${...}``) are NOT violations — the
        # executor handles those.
        for node in nodes:
            op = str(node.get("op") or "")
            bad = _schema_type_violations(op, node.get("inputs") or {})
            if bad:
                detail = "; ".join(
                    f"{k}={v!r} (declared {declared})" for k, v, declared in bad
                )
                violations.append(Violation(
                    code="wrong_type",
                    severity=ViolationSeverity.ERROR,
                    action=ViolationAction.DROP_OP,
                    node=op,
                    message=f"{op} input type violations: {detail}",
                ))
                errors.append(f"{op} input type violations: {detail}")

        # 3c. UNKNOWN INPUT KEYS (D0/P0-C, I11): an input key the
        # capability schema does not declare (and is not an x-alias) is an
        # invented parameter — the tool never consumes it, the plan is
        # structurally invalid, and it must never be cached or executed.
        for node in nodes:
            op = str(node.get("op") or "")
            node_inputs = node.get("inputs") or {}
            if not isinstance(node_inputs, dict):
                continue
            bad = _unknown_input_keys(op, node_inputs)
            if bad:
                violations.append(Violation(
                    code="unknown_input_key",
                    severity=ViolationSeverity.ERROR,
                    action=ViolationAction.REFINE,
                    node=op,
                    message=(
                        f"{op} declares input keys not in its schema: "
                        f"{', '.join(sorted(bad))}"
                    ),
                ))
                errors.append(
                    f"{op} unknown input keys: {', '.join(sorted(bad))}"
                )

        # 3b2. PARAMETER PROVENANCE (P0): a planned input VALUE must be
        # traceable to the user request or a producer chain — never an LLM
        # guess. "Correct operation + wrong parameter" (e.g. hardcoded Tokyo
        # coordinates for an Islamabad weather query) passes every structural
        # check yet answers the wrong thing. Provenance is metadata-free:
        #   - ``${...}`` placeholder        → artifact_reference (chained) ✓
        #   - value appears in the request  → user_literal ✓
        #   - otherwise                     → llm_literal (guessed) ✗
        # Guessed values on REQUIRED inputs trigger a bounded repair so the
        # planner chains the producer instead.
        if user_query:
            for node in nodes:
                op = str(node.get("op") or "")
                node_inputs = node.get("inputs") or {}
                if not isinstance(node_inputs, dict):
                    continue
                required = set(_capability_meta(op).get("input_required") or [])
                for key, value in node_inputs.items():
                    if key not in required:
                        continue
                    if isinstance(value, str) and (
                        not value.strip() or value.startswith("${")
                        or _is_chain_expression(value)
                    ):
                        continue
                    if not isinstance(value, (str, int, float)):
                        continue
                    if _value_in_message(value, user_query):
                        continue
                    violations.append(Violation(
                        code="parameter_provenance",
                        severity=ViolationSeverity.ERROR,
                        action=ViolationAction.REFINE,
                        node=op,
                        message=(
                            f"{op} input '{key}'={value!r} is not traceable to "
                            f"the user request or a producer chain — chain the "
                            f"producer or use the user's own value"
                        ),
                    ))
                    errors.append(
                        f"{op} parameter '{key}' lacks provenance (guessed value)"
                    )
                    break

        # 3c. Continuation completeness (Phase 3): when the user is continuing
        # the PREVIOUS turn's chain ("And in Osaka?" after a weather query)
        # and the plan includes a prior-chain PRODUCER without its CONSUMER,
        # the plan is incomplete — the producer's output feeds the consumer
        # (metadata-driven via produces/consumes). Refine (replan) with the
        # feedback so the consumer step is included.
        if prior_chain:
            planned_ops = {str(n.get("op") or "") for n in nodes if isinstance(n, dict)}
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                op = str(node.get("op") or "")
                if op not in prior_chain or op in planned_ops - {op}:
                    continue
                idx = prior_chain.index(op)
                produced = set(_capability_meta(op).get("produces") or [])
                for later in prior_chain[idx + 1:]:
                    later_meta = _capability_meta(later)
                    if produced & set(later_meta.get("consumes") or []):
                        if later not in planned_ops:
                            violations.append(Violation(
                                code="missing_consumer",
                                severity=ViolationSeverity.ERROR,
                                action=ViolationAction.REFINE,
                                node=op,
                                message=(
                                    f"{op} produces data consumed by {later} "
                                    f"(previous chain) — include the consumer step"
                                ),
                            ))
                            errors.append(f"{op} missing consumer {later}")
                        break

        # 3d. Producer completeness (Step 7): a planned node with a REQUIRED
        # input carrying a LITERAL value, where a REGISTERED capability
        # produces that artifact AND the producer's own required inputs are
        # satisfiable from the plan (a literal anywhere in the plan or an
        # output of a planned op) — i.e. the producer chain is actually
        # constructible ("consumes a value the query supplies") — while the
        # producer itself is absent from the plan → the literal was
        # guessed/derivable. REFINE so the planner justifies or chains —
        # metadata-driven via produces/consumes/input_required. Literal
        # inputs stay legitimate when no producer exists or the chain is not
        # constructible from the plan.
        planned_ops = {str(n.get("op") or "") for n in nodes if isinstance(n, dict)}
        planned_keys: set[str] = set()
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_inputs = node.get("inputs") or {}
            if isinstance(node_inputs, dict):
                planned_keys.update(node_inputs.keys())
        planned_outputs: set[str] = set()
        for op in planned_ops:
            planned_outputs.update(_capability_meta(op).get("produces") or [])
        for node in nodes:
            if not isinstance(node, dict):
                continue
            op = str(node.get("op") or "")
            if op not in valid_ops:
                continue
            node_inputs = node.get("inputs") or {}
            if not isinstance(node_inputs, dict):
                continue
            required = set(_capability_meta(op).get("input_required") or [])
            if not required:
                continue
            for key, value in node_inputs.items():
                if key not in required:
                    continue
                if isinstance(value, str) and (
                    not value.strip() or value.startswith("${")
                ):
                    continue
                if not isinstance(value, (str, int, float, bool)):
                    continue
                producers = _producer_ops(key) - {op} - planned_ops
                constructible = {
                    p for p in producers
                    if _chain_constructible(p, planned_keys, planned_outputs)
                }
                if constructible:
                    producer_names = ", ".join(sorted(constructible))
                    violations.append(Violation(
                        code="missing_producer",
                        severity=ViolationSeverity.ERROR,
                        action=ViolationAction.REFINE,
                        node=op,
                        message=(
                            f"{op} input '{key}' has a literal value but is "
                            f"producible by: {producer_names} — chain the "
                            f"producer or justify the literal"
                        ),
                    ))
                    errors.append(f"{op} missing producer for {key}")
                    break

        # 3e. INTENT COVERAGE + TRACEABILITY (P4-1): the semantic
        # completeness pair. COVERAGE asks "was every intent served?";
        # TRACEABILITY asks "did every planned op come from an intent?" —
        # together they eliminate omission (T1/T2/T8) and invention (T5).
        # Metadata-driven: unit→capability via the registry keyword index.
        if detected is not None and detected.units:
            planned_ops = {str(n.get("op") or "") for n in nodes if isinstance(n, dict)}

            def _unit_classifiable(u: Any) -> bool:
                """P0-C: a unit is classifiable when the keyword bridge sees
                it OR the deterministic engine ranked capabilities for it
                (structured-intent goals — the K83 "find the address at the
                coordinate" goal has no keyword-bridge hit but the engine
                ranks reverse_geocode for it). Engine rank is the same
                signal the planner's branch resolution used, so coverage
                and resolution never disagree about intent existence.

                P1-A FLOOR: an engine hit at KEYWORD-NOISE scale (sub-
                floor — the V134 fragments "failed operations" / "final
                usable artifacts" pick up 1-5.0 noise candidates from
                unrelated capabilities) does NOT make a fragment an
                executable intent. A noise-classifiable unit that is
                unserved must never REFINE the whole plan — the reviewer's
                L5: weak signals are confidence hints, not rejections.
                """
                if _unit_candidates(u):
                    return True
                _strong = [
                    (n, s) for n, s in (engine_scores or {}).get(u.text, [])
                    if s >= _ALIGNMENT_DOMINANCE_FLOOR
                ]
                return bool(_strong)

            executable = [
                u for u in detected.units
                if not u.negated and _unit_classifiable(u)
            ]
            # UNCLASSIFIABLE units (no keyword/alias/name signal — e.g. a
            # unit carrying only an entity like a city name) are excluded
            # from coverage: the check catches DROPPED known intents, not
            # entities the keyword bridge cannot see.
            unclassifiable = [
                u.text for u in detected.units
                if not u.negated and not _unit_classifiable(u)
            ]
            negated = [u for u in detected.units if u.negated]
            forbidden_ops = set()
            for u in negated:
                forbidden_ops |= _unit_candidates(u)
            served: list[str] = []
            dropped: list[str] = []
            # PER-INTENT EVIDENCE (I4, P0-B): one structured record per
            # intent unit — candidates, planned matches, chosen vs best
            # capability, alignment and served status. The scalar
            # intent_coverage metric stays for dashboards; the evidence is
            # the debuggable truth the validator and telemetry consume.
            # ALIGNMENT SEMANTICS (B3, engine-score based): the alignment
            # verdict comes from the DETERMINISTIC resolver's per-unit
            # SCORES (engine_top/engine_dominant/engine_verdict) — never a
            # keyword-bridge proxy, never whole-query rank positions alone.
            coverage_evidence: list[dict[str, Any]] = []
            for u in detected.units:
                candidates = _unit_candidates(u)
                engine_ranked = (engine_scores or {}).get(u.text, [])
                # P0-C: engine-ranked names extend the candidate set — the
                # structured-intent goals the keyword bridge cannot see.
                engine_names = {n for n, _s in engine_ranked}
                all_candidates = candidates | engine_names
                classifiable = (bool(all_candidates)) and not u.negated
                matches = planned_ops & all_candidates if classifiable else set()
                best = _best_capability(u, all_candidates) if all_candidates else None
                chosen = (
                    _best_capability(u, matches)
                    if matches else None
                )
                engine_verdict = _alignment_verdict(chosen, engine_ranked)
                engine_top = engine_ranked[0][0] if engine_ranked else None
                engine_dominant = _engine_dominant(engine_ranked)
                coverage_evidence.append({
                    "unit": u.text,
                    "negated": u.negated,
                    "classifiable": classifiable,
                    "instance_hint": u.instance_hint,
                    "candidates": sorted(all_candidates),
                    "planned_matches": sorted(matches),
                    "best": best,
                    "chosen": chosen,
                    "engine_top": engine_top,
                    "engine_dominant": engine_dominant,
                    "engine_verdict": engine_verdict,
                    "aligned": engine_verdict == "aligned",
                    "served": None,  # filled below for executable units
                })
            for u in executable:
                candidates = _unit_candidates(u)
                engine_ranked = (engine_scores or {}).get(u.text, [])
                engine_names = {n for n, _s in engine_ranked}
                matches = planned_ops & (candidates | engine_names)
                instance_need = max(1, u.instance_hint)
                if len(matches) >= instance_need and not (matches & forbidden_ops):
                    served.append(u.text)
                else:
                    dropped.append(u.text)
            for rec, u in zip(coverage_evidence, detected.units, strict=True):
                if not u.negated and rec["classifiable"]:
                    rec["served"] = u.text in served
            metrics["intent_coverage_evidence"] = coverage_evidence
            metrics["detected_executable"] = len(executable)
            metrics["unclassifiable_units"] = len(unclassifiable)
            metrics["served_intents"] = len(served)
            metrics["dropped_intents"] = len(dropped)
            metrics["intent_coverage"] = (
                round(len(served) / len(executable), 3) if executable else 1.0
            )
            # CAPABILITY ALIGNMENT (B3, engine-score based): a served unit
            # may still be served by the WRONG capability. The alignment
            # verdict comes from the DETERMINISTIC resolver's per-unit
            # SCORES: a pick that differs from the engine's top candidate
            # BLOCKS (ERROR/REFINE) only when the engine evidence is STRONG
            # (unique or dominant top). Close/weak signals are ambiguous —
            # evidence only, never blocking (the historical false-positive
            # class: scenarios 8/20/38/47 lived in weak-signal territory).
            misaligned: list[str] = []
            alignments: list[float] = []
            for u in executable:
                candidates = _unit_candidates(u)
                engine_names = {n for n, _s in (engine_scores or {}).get(u.text, [])}
                matches = planned_ops & (candidates | engine_names)
                if not matches:
                    continue
                chosen = _best_capability(u, matches)
                engine_ranked = (
                    alignment_scores or {}
                ).get(u.text) or (engine_scores or {}).get(u.text, [])
                verdict = _alignment_verdict(chosen, engine_ranked)
                if verdict == "misaligned":
                    top = engine_ranked[0][0] if engine_ranked else "?"
                    misaligned.append(f"{u.text[:40]} -> {chosen} (engine best: {top})")
                    alignments.append(0.0)
                    logger.info(
                        "plan_validator.alignment_misaligned",
                        unit=u.text[:60],
                        chosen=chosen,
                        engine_top=top,
                        engine=engine_ranked[:4],
                        candidates=sorted(candidates | {n for n, _s in engine_ranked})[:6],
                    )
                elif verdict == "aligned":
                    alignments.append(1.0)
                    # P0-D.1 alignment evidence trail (the reviewer's
                    # CapabilityAlignment record) — every ACCEPT is
                    # explainable: lexical + semantic (generic-filtered)
                    # scores, domain/alias/produces signals, decision.
                    _aligned_ev = {
                        "capability_id": chosen,
                        "intent_id": u.text[:80],
                        "lexical_score": round(
                            (engine_scores or {}).get(u.text, [(None, 0.0)])[0][1], 2
                        ),
                        "semantic_score": round(
                            engine_ranked[0][1] if engine_ranked else 0.0, 2
                        ),
                        "domain_match": bool(
                            _unit_candidates(u) & {chosen}
                        ),
                        "resolver_evidence": bool(
                            chosen in {n for n, _s in (engine_scores or {}).get(u.text, [])}
                        ),
                        "decision": "ACCEPT",
                    }
                    metrics.setdefault("alignment_evidence", []).append(_aligned_ev)
                else:
                    alignments.append(1.0)  # ambiguous/no_signal: not a defect
            metrics["capability_alignment"] = (
                round(sum(alignments) / len(alignments), 3) if alignments else 1.0
            )
            if misaligned:
                violations.append(Violation(
                    code="capability_alignment",
                    severity=ViolationSeverity.ERROR,
                    action=ViolationAction.REFINE,
                    node="plan",
                    message=(
                        "planned capability is not the engine's dominant "
                        f"candidate for the intent unit: {'; '.join(misaligned[:4])}"
                    ),
                ))
                errors.append(
                    f"capability alignment {metrics['capability_alignment']:.0%}"
                )
            # Coverage violations: every executable unit must be served.
            if dropped:
                violations.append(Violation(
                    code="intent_coverage",
                    severity=ViolationSeverity.ERROR,
                    action=ViolationAction.REFINE,
                    node="plan",
                    message=(
                        "detected intent units not served by any planned "
                        f"capability: {', '.join(dropped[:5])}"
                    ),
                ))
                errors.append(
                    f"intent coverage {metrics['intent_coverage']:.0%} "
                    f"({len(dropped)} dropped): {', '.join(dropped[:5])}"
                )
            # Traceability violations: every planned op must trace to a
            # non-negated unit's candidates OR be a producer feeding a
            # consumed artifact of another planned op (the chained
            # producer exemption). Ops matching a NEGATED unit's
            # candidates are forbidden outright.
            # NO-SIGNAL RULE: the negative requires at least one
            # CLASSIFIABLE unit — when the semantic bridge yields no
            # candidates at all (a weak keyword map for the query's
            # vocabulary), traceability has no signal and must not flag
            # every op as invented (false positives).
            extraneous: list[str] = []
            if executable or forbidden_ops:
                planned_consumes = set()
                for n in nodes:
                    if isinstance(n, dict):
                        planned_consumes |= set(
                            _capability_meta(str(n.get("op") or "")).get("consumes") or []
                        )
                for op in sorted(planned_ops):
                    if op in forbidden_ops:
                        extraneous.append(op)
                        continue
                    if any(op in _unit_candidates(u) for u in executable):
                        continue
                    produced = set(_capability_meta(op).get("produces") or [])
                    if produced & planned_consumes:
                        continue  # chained producer feeds a planned consumer
                    extraneous.append(op)
            metrics["extraneous_operations"] = extraneous
            metrics["extraneous_operation_rate"] = (
                round(len(extraneous) / len(planned_ops), 3) if planned_ops else 0.0
            )
            if extraneous:
                # TRACEABILITY PRECISION (P0): ops forbidden by NEGATION are
                # hard errors (never execute what the user excluded). The
                # non-forbidden class is a WARNING — its precision is
                # bounded by the keyword-map quality (a weak bridge can
                # mis-flag a legitimately planned op); the bounded repair
                # runs, then the plan proceeds with the signal recorded.
                if forbidden_ops:
                    violations.append(Violation(
                        code="extraneous_operation",
                        severity=ViolationSeverity.ERROR,
                        action=ViolationAction.DROP_OP,
                        node="plan",
                        message=(
                            "operations forbidden by user negation: "
                            f"{', '.join(sorted(forbidden_ops & set(extraneous))[:5])}"
                        ),
                    ))
                violations.append(Violation(
                    code="extraneous_operation",
                    severity=ViolationSeverity.WARNING,
                    action=ViolationAction.REFINE,
                    node="plan",
                    message=(
                        "planned operations trace to no detected intent unit: "
                        f"{', '.join(extraneous[:5])}"
                    ),
                ))
                errors.append(
                    f"extraneous operations: {', '.join(extraneous[:5])}"
                )

        # 4. Budget estimate (metadata-driven cost from provider metadata).
        if self.budget_cap_usd is not None:
            cost = _estimate_cost(nodes)
            if cost > self.budget_cap_usd:
                violations.append(Violation(
                    code="budget",
                    severity=ViolationSeverity.ERROR,
                    action=ViolationAction.REFINE,
                    node="plan",
                    message=f"estimated cost ${cost:.4f} exceeds cap ${self.budget_cap_usd:.4f}",
                ))
                errors.append("budget exceeded")

        # 5. Policy/permission pre-check (approval/risk — informational here;
        # the ApprovalGateNode remains the enforcement point).
        for node in nodes:
            op = str(node.get("op") or "")
            if _requires_approval(op):
                violations.append(Violation(
                    code="approval_required",
                    severity=ViolationSeverity.WARNING,
                    action=ViolationAction.APPROVAL,
                    node=op,
                    message=f"{op} requires approval (risk/approval metadata)",
                ))

        valid = not any(
            v.severity in (ViolationSeverity.CRITICAL, ViolationSeverity.ERROR)
            for v in violations
        )
        return PlanValidatorReport(
            valid=valid,
            violations=tuple(violations),
            errors=errors,
            metrics=metrics,
        )


# ---------------------------------------------------------------------------
# Pure module-level helpers (side-effect free; GC reads only)
# ---------------------------------------------------------------------------


def _valid_op_names() -> set[str]:
    """Resolved capability names from GlobalContext (metadata-driven)."""
    try:
        return set((getattr(_gc_mod.get_global_context(), "capability_index", {}) or {}).keys())
    except Exception:
        return set()


def _capability_meta(op: str) -> dict[str, Any]:
    try:
        return (getattr(_gc_mod.get_global_context(), "capability_index", {}) or {}).get(op, {})
    except Exception:
        return {}


def _producer_ops(artifact: str) -> set[str]:
    """Registered capabilities whose ``produces`` list contains the artifact.

    Metadata-driven (GlobalContext capability_index produces/consumes) —
    the set of ops that can DERIVE a given input value.
    """
    producers: set[str] = set()
    try:
        index = getattr(_gc_mod.get_global_context(), "capability_index", {}) or {}
    except Exception:
        return producers
    for name, meta in index.items():
        if not isinstance(meta, dict):
            continue
        produces = meta.get("produces") or []
        if isinstance(produces, list) and artifact in produces:
            producers.add(str(name))
    return producers


def _chain_constructible(
    producer: str,
    planned_keys: set[str],
    planned_outputs: set[str],
) -> bool:
    """A producer chain is constructible when the producer's own required
    inputs are satisfiable from the plan — an input KEY present anywhere in
    the plan, or an artifact produced by another planned op. Purely
    structural/metadata-driven: no extraction, no guessing.
    """
    required = set(_capability_meta(producer).get("input_required") or [])
    if not required:
        return False
    return required <= planned_keys or required <= planned_outputs


def _detect_intents(user_query: str):
    """Deterministic Tier-1 intent decomposition (P4) — None on failure."""
    try:
        from nexus.agent.planners.intent_detector import IntentDetector

        return IntentDetector().detect(user_query)
    except Exception:
        return None


def _structured_to_detected(structured: dict[str, Any]):
    """P0-C bridge: the planner's structured intent graph (goals, not tools)
    onto the validator's ``DetectedIntents`` unit shape.

    Each structured intent becomes one ``IntentUnit`` whose text is its
    GOAL (the resolver's keyword bridge classifies goals — the K83
    "reverse geocode the coordinates" goal carries the reverse-geocode
    signal the raw clause splitter never emitted).
    """
    try:
        from nexus.agent.planners.intent_detector import DetectedIntents, IntentUnit

        raw = structured.get("intents") or []
        if not isinstance(raw, list):
            return None
        units = []
        for order, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            goal = str(item.get("goal") or "").strip()
            if not goal:
                continue
            units.append(IntentUnit(
                text=goal,
                negated=bool(item.get("negated", False)),
                order=int(item.get("sequence", order) or order),
                instance_hint=1,
                comparison=False,
                confidence=float(item.get("confidence", 1.0) or 1.0),
            ))
        if not units:
            return None
        return DetectedIntents(units=tuple(units), confidence=1.0, source="llm")
    except Exception:
        return None


def _has_executable_units(detected) -> bool:
    return any(not u.negated and _unit_candidates(u) for u in detected.units)


def _units_text(detected) -> str:
    return "; ".join(u.text[:60] for u in detected.units[:5])


def _unit_candidates(unit) -> frozenset[str]:
    """Metadata-driven unit→capability bridge (registry keyword index)."""
    try:
        from nexus.agent.planners.intent_detector import unit_candidates

        return unit_candidates(unit, _gc_mod.get_global_context())
    except Exception:
        return frozenset()


def _best_capability(unit, ops) -> str | None:
    """Deterministic best-capability pick: highest keyword/name/alias
    match strength, name-lexicographic tiebreak (B3/P0-B)."""
    ranked = sorted(ops, key=lambda c: (_op_match_strength(unit, c), str(c)))
    return str(ranked[-1]) if ranked else None


def _op_match_strength(unit, op: str) -> int:
    """Keyword/name/alias match strength between an intent unit and a
    capability — used for the capability-alignment ranking. Metadata-only
    (registry keyword map + capability-name tokens); no hardcoded logic."""
    import re as _re

    try:
        gc = _gc_mod.get_global_context()
        tokens = set(_re.findall(r"[a-zA-Z]+", unit.text.lower()))
        strength = 0
        keyword_map = getattr(gc, "capability_keywords", None) or {}
        for kw, caps in keyword_map.items():
            if kw in tokens and op in caps:
                strength += 1
        alias_index = getattr(gc, "alias_index", None) or {}
        for token in tokens:
            if op in (alias_index.get(token) or []):
                strength += 1
        name_tokens = set(_re.findall(r"[a-zA-Z]+", op.lower()))
        strength += len(name_tokens & tokens)
        return strength
    except Exception:
        return 0


def _is_chain_expression(value: str) -> bool:
    """True for the declarative producer-chain expression forms the planner
    may emit instead of ``${ref.result.field}`` placeholders — the
    ``RESOLVE("capability", "input_key", "value")`` form (declares a
    producer capability, its input key, and the value) and the ``{{ref}}``
    double-brace reference variant. They are chain requests, never guessed
    literals (exempt from provenance and type checks; the compiler/executor
    translate or reject them explicitly)."""
    s = value.strip()
    if s.startswith("RESOLVE(") and s.endswith(")"):
        return True
    return s.startswith("{{") and s.endswith("}}")


# B3 (P0-B deferred, now landed): ENGINE-SCORE ALIGNMENT.
# The engine's top candidate must constitute STRONG evidence to BLOCK:
# - with a runner-up: top outscores it by ``_ALIGNMENT_DOMINANCE_RATIO``
#   AND the top clears ``_ALIGNMENT_DOMINANCE_FLOOR`` (P1-A: the ratio
#   alone trips on tiny absolute scores — geocode 5.0 vs 1.0 for "the
#   failing probe" is keyword noise, not dominance; the engine's strong
#   signal class is the exact-alias 100.0 hit. The reviewer's L5: weak
#   signals are confidence hints, never hard rejections);
# - UNIQUE top (no runner-up): its score must reach
#   ``_ALIGNMENT_STRONG_MIN_SCORE`` — a lone weak keyword hit (e.g. a
#   single ``keyword:day`` noise candidate at score 3.0) is NOT strong
#   evidence (the Bitcoin-price class: the engine's only hit was an
#   astronomy-pic noise match while the correct capability was absent).
# Anything else is ambiguous (evidence only) — the historical false
# positives (scenarios 8/20/38/47) all lived in weak/close territory.
_ALIGNMENT_DOMINANCE_RATIO = 2.0
_ALIGNMENT_STRONG_MIN_SCORE = 5.0
# Ratio-path absolute floor: below this the top is keyword-scale noise
# (engine keyword/example hits score 1-5; the exact-alias class is 100).
_ALIGNMENT_DOMINANCE_FLOOR = 10.0


def _engine_dominant(engine_ranked: list[tuple[str, float]]) -> bool:
    """True when the engine's top candidate is STRONG evidence (unique
    high-score, or dominant over the runner-up AND strong in absolute
    terms — P1-A floor so tiny-score ratios never block)."""
    if not engine_ranked:
        return False
    top_score = engine_ranked[0][1]
    if len(engine_ranked) == 1:
        return top_score >= _ALIGNMENT_STRONG_MIN_SCORE
    runner_up = engine_ranked[1][1]
    if top_score < _ALIGNMENT_DOMINANCE_FLOOR:
        return False  # keyword-noise top: ambiguous, never blocking
    return top_score >= runner_up * _ALIGNMENT_DOMINANCE_RATIO


_SEMANTICS_MAP_CACHE: dict[str, Any] | None = None


async def _load_semantics_map() -> dict[str, Any]:
    """CapabilitySemantics map from the registry tool rows — the SAME
    metadata the resolver's branch ranker consumes (P0-A). Cached per
    process; the registry is immutable per deployment."""
    global _SEMANTICS_MAP_CACHE
    if _SEMANTICS_MAP_CACHE is not None:
        return _SEMANTICS_MAP_CACHE
    semantics: dict[str, Any] = {}
    try:
        from sqlalchemy import select as _sem_select  # noqa: PLC0415

        from nexus.capabilities.capability_semantics import (  # noqa: PLC0415
            CapabilitySemantics,
        )
        from nexus.db.base import async_session as _sem_db  # noqa: PLC0415
        from nexus.db.models.tool import Tool  # noqa: PLC0415

        async with _sem_db() as _s:
            _rows = await _s.execute(
                _sem_select(
                    Tool.name, Tool.validation_rules, Tool.input_schema,
                    Tool.consumes, Tool.produces, Tool.category,
                )
            )
            for _r in _rows.all():
                try:
                    semantics[str(_r[0])] = CapabilitySemantics.from_registry(
                        str(_r[0]), _r
                    )
                except Exception:
                    pass
    except Exception as _sem_exc:
        logger.warning("plan_validator.semantics_load_failed", error=str(_sem_exc)[:150])
    _SEMANTICS_MAP_CACHE = semantics
    return semantics


async def _semantic_filter_engine(
    engine_ranked: list[tuple[str, float]],
    unit_text: str,
) -> list[tuple[str, float]]:
    """P0-D.1: apply the P0-A generic-suppression semantics to the engine's
    raw per-unit scores BEFORE the alignment verdict.

    The raw engine scores are scale-incomparable across layers: the
    generic "search" alias fires at 100.0 for any query containing
    "search", while the SPECIALIZED capability (search_universities at
    5.0) wins the resolver's branch. The validator must judge alignment
    on the SAME representation the resolver uses (CapabilitySemantics) —
    otherwise a correct specialized pick is rejected because the generic
    fallback outscored it in raw terms (the D48/D49 class).

    Metadata-driven (generic/fallback flags + specificity), never a
    capability-name list.
    """
    if len(engine_ranked) < 2:
        return engine_ranked
    semantics = await _load_semantics_map()
    if not semantics:
        return engine_ranked
    web_tokens = set(re.findall(r"[a-zA-Z]+", (unit_text or "").lower()))
    explicit_web = bool(web_tokens & {"web", "internet", "online"})
    specialized = [
        (name, score)
        for name, score in engine_ranked
        if not getattr(semantics.get(name), "generic", False)
        and not getattr(semantics.get(name), "fallback", False)
    ]
    if specialized and not explicit_web:
        return [s for s in engine_ranked if s[0] in {n for n, _s in specialized}]
    return engine_ranked


def _alignment_verdict(
    chosen: str | None,
    engine_ranked: list[tuple[str, float]],
) -> str:
    """Pure B3 verdict for one intent unit.

    Args:
        chosen: The capability the plan assigned to the unit (its best
            planned match), or None when the unit is unserved.
        engine_ranked: The deterministic resolver's ranked candidates for
            the unit as ``(name, score)`` pairs (highest first).

    Returns:
        One of:
        - ``aligned``: the plan's pick is the engine's top candidate
          (never blocks).
        - ``misaligned``: the plan's pick differs from the engine's top
          AND the engine evidence is STRONG (dominant over the runner-up,
          or a unique top at/above ``_ALIGNMENT_STRONG_MIN_SCORE``; this
          covers a pick absent from the candidate set when the evidence
          is strong). BLOCKING grade.
        - ``ambiguous``: the pick differs but the engine evidence is
          CLOSE or weak (no dominance, or a unique sub-floor noise hit) —
          evidence only, never blocks.
        - ``no_signal``: no pick or no engine candidates — the existing
          unresolved/coverage behavior applies untouched.
    """
    if not chosen or not engine_ranked:
        return "no_signal"
    top_name, _top_score = engine_ranked[0]
    if chosen == top_name:
        return "aligned"
    if _engine_dominant(engine_ranked):
        return "misaligned"
    return "ambiguous"


async def _engine_ranked_for_unit(unit_text: str) -> list[tuple[str, float]]:
    """Deterministic resolver ranking for a single intent unit.

    The engine is GC-only (no DB, no LLM) — a few extra deterministic
    calls per validation are bounded by the repair-round cap. Scores are
    the ACTUAL resolver scores (exact_alias=100, keyword/example signals),
    never a keyword-strength proxy. Degrades to ``[]`` (no_signal) on any
    failure — B3 must never break validation.
    """
    try:
        from nexus.capabilities.resolution_engine import get_resolution_engine  # noqa: PLC0415

        res = await get_resolution_engine().resolve(unit_text, top_k=15)
        return [
            (c.name, float(c.score))
            for c in res.capability_candidates
        ]
    except Exception as exc:
        logger.warning("plan_validator.engine_rank_failed", error=str(exc)[:150])
        return []


def _semantic_cache_eligible(report: PlanValidatorReport) -> bool:
    """SEMANTIC CACHE ELIGIBILITY (P2F): a plan may persist in the parse
    cache only when the validator's full verdict is clean:

    - report VALID (no ERROR/CRITICAL violation — REFINE/ABORT verdicts
      are never cache-eligible);
    - intent coverage == 100% (a partial-execution plan — coverage < 1.0 —
      must never be replayed);
    - no capability_alignment violation (a misaligned plan must never be
      replayed).

    Structural safety (schema/provenance, I11) is enforced at write time by
    the planner's ``_plan_unsafe_to_cache``; compile success is enforced by
    the compiler removing the entry on failure. Together they form the
    cache-eligibility contract: syntactically valid is NOT semantically
    safe.
    """
    if not report.valid:
        return False
    if report.metrics.get("intent_coverage", 1.0) != 1.0:
        return False
    if any(v.code == "capability_alignment" for v in report.violations):
        return False
    return True


async def _remove_semantically_ineligible_plan(snapshot: dict[str, Any], reason: str) -> None:
    """Remove the parse-cache entry for the current query after a semantic
    rejection (P2F gatekeeper).

    The planner writes the cache BEFORE validation (the validator is the
    next node), so the semantic verdict cannot gate the write — instead the
    validator/compiler REMOVE the entry the moment the verdict is not
    cache-eligible. Net effect: only semantically-passing plans persist,
    and pre-rule entries self-heal (removed the first time they are
    rejected). The key replicates the planner's key exactly (query +
    context chain + model + architecture/prompt fingerprints via the cache
    builder) — degrade-safe: any failure only leaves the entry in place.
    """
    try:
        from nexus.agent.nodes.semantic_parser_node import _prior_plan_context  # noqa: PLC0415
        from nexus.compiler.cache import get_parse_cache  # noqa: PLC0415
        from nexus.config.settings import get_settings  # noqa: PLC0415

        user_query = _current_user_query(snapshot)
        if not user_query:
            return
        _, prior_chain = _prior_plan_context(snapshot)
        model = get_settings().llm.default_model
        await get_parse_cache().remove(user_query, [], model, context=prior_chain)
        logger.info("plan_cache.semantic_removed", reason=reason)
    except Exception as exc:
        logger.warning("plan_cache.semantic_remove_failed", error=str(exc)[:150])


def _current_user_query(state: dict[str, Any]) -> str | None:
    """The LAST user message (the current request — never the history)."""
    messages = state.get("messages") or []
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return content
    return None


def _value_in_message(value: Any, message: str) -> bool:
    """True when the value is plausibly derived from the user's request.

    Canonical matching: the value's string form AND its normalized numeric
    forms (trailing-zero-trimmed) are searched case-insensitively, so
    ``34`` matches "34 degrees" and ``34.0`` matches "34.5" only when the
    digits actually appear. Pure structural comparison — no word lists.
    """
    if not message:
        return False
    haystack = message.lower()
    candidates: list[str] = [str(value).lower().strip()]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and value.is_integer():
            candidates.append(str(int(value)))
        candidates.append(f"{value:g}")
    return any(c and c in haystack for c in candidates)


def _prior_executed_chain(state: dict[str, Any]) -> list[str] | None:
    """The PREVIOUS turn's executed tool chain, in execution order.

    Reads the state's execution graph (waves → task ids → tool names).
    Returns None when there is no prior execution (a fresh query has no
    continuation context). Metadata-driven — no hardcoded names.
    """
    graph = state.get("_execution_graph") or {}
    if not isinstance(graph, dict):
        return None
    nodes = graph.get("nodes")
    waves = graph.get("waves")
    if not isinstance(nodes, dict) or not nodes:
        return None
    tool_by_id: dict[str, str] = {}
    for nid, ndata in nodes.items():
        if not isinstance(ndata, dict):
            continue
        name = ndata.get("tool_name") or ndata.get("capability") or ""
        if name:
            tool_by_id[str(nid)] = str(name)
    ordered: list[str] = []
    if isinstance(waves, list):
        for wave in waves:
            if not isinstance(wave, dict):
                continue
            for tid in (wave.get("tasks") or []):
                if str(tid) in tool_by_id:
                    ordered.append(tool_by_id[str(tid)])
    if not ordered:
        ordered = list(tool_by_id.values())
    return ordered or None


def _find_cycle(nodes: list[dict[str, Any]]) -> list[str]:
    """DFS cycle detection over depends_on refs; returns cycle path or [].

    Mirrors the compiler's static dataflow: adjacency includes BOTH the
    explicit ``depends_on`` refs AND the implicit edges the compiler wires
    from ``${ref.result...}`` input placeholders — a plan the validator
    clears but the compiler rejects is a plan the validator should have
    caught (the follow-up class: mutual placeholder refs between nodes).
    """
    import re as _re

    names = [
        str(n.get("ref") or n.get("op") or "")
        for n in nodes
    ]
    index: dict[str, int] = {}
    for i, node in enumerate(nodes):
        index[str(node.get("ref") or node.get("op") or "")] = i
        if node.get("ref") and node.get("op"):
            index[str(node.get("op"))] = i  # legacy op-named deps still resolve
    adj: dict[str, list[str]] = {n: [] for n in names}
    placeholder_re = _re.compile(r"\$\{([a-zA-Z0-9_]+)\.result")
    for node in nodes:
        src = str(node.get("ref") or node.get("op") or "")
        deps: set[str] = set()
        for dep_raw in (node.get("depends_on") or []):
            dep_name = str(dep_raw)
            if dep_name in index:
                deps.add(names[index[dep_name]])
        node_inputs = node.get("inputs") or {}

        def _scan(value: Any) -> None:
            if isinstance(value, dict):
                for v in value.values():
                    _scan(v)
            elif isinstance(value, (list, tuple)):
                for v in value:
                    _scan(v)
            elif isinstance(value, str):
                for match in placeholder_re.finditer(value):
                    ref = match.group(1)
                    if ref in index:
                        deps.add(names[index[ref]])

        _scan(node_inputs)
        adj[src].extend(d for d in sorted(deps) if d in adj)

    state: dict[str, int] = {}  # 0=visiting 1=done
    path: list[str] = []

    def dfs(n: str) -> list[str]:
        state[n] = 0
        path.append(n)
        for m in adj.get(n, []):
            if m not in state:
                cycle = dfs(m)
                if cycle:
                    return cycle
            elif state[m] == 0:
                start = path.index(m)
                return path[start:] + [m]
        path.pop()
        state[n] = 1
        return []

    for n in names:
        if n not in state:
            cycle = dfs(n)
            if cycle:
                return cycle
    return []


def _missing_inputs(op: str, provided: set[str]) -> set[str]:
    """Required schema inputs (GC meta, from the tool's input_schema) the
    plan does not provide. Alias-aware: a provided key that is an x-alias of
    a required property counts as satisfied (the executor remaps it at call
    time). Empty/whitespace values count as NOT provided (a plan that emits
    ``latitude: ""`` has no usable input — it would fail at execution with
    a type error). No schema — nothing reported (never guesses)."""
    if not op:
        return set()
    meta = _capability_meta(op)
    required = set(meta.get("input_required") or [])
    if not required:
        return set()
    provided_aliases: set[str] = set()
    alias_map = meta.get("input_aliases") or {}
    for key in provided:
        for prop_name, aliases in alias_map.items():
            if key in aliases:
                provided_aliases.add(prop_name)
    satisfied = provided | provided_aliases
    return required - satisfied


def _unknown_input_keys(op: str, inputs: dict[str, Any]) -> list[str]:
    """Input keys the capability schema does not declare (D0/P0-C, I11).

    An invented key (``base_currency`` on a tool whose schema declares
    other properties, or any LLM-invented parameter) is never consumed by
    the tool — the plan is structurally invalid. Alias-aware (x-alias keys
    declared in ``input_aliases`` are valid). No declared schema → no
    signal → nothing reported (never guesses).
    """
    if not op:
        return []
    meta = _capability_meta(op)
    schema = meta.get("input_schema") or {}
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict) or not props:
        return []
    declared = set(props)
    alias_map = meta.get("input_aliases") or {}
    for aliases in alias_map.values():
        declared.update(str(a) for a in (aliases or []))
    return [
        str(k) for k in (inputs or {}).keys()
        if str(k) not in declared
    ]


def _schema_type_violations(op: str, inputs: dict) -> list[tuple[str, Any, str]]:
    """Input values that can never satisfy the op's declared JSON Schema types.

    Metadata-driven (GC meta ``input_schema`` from the tool registry): a
    declared ``boolean`` receiving an arbitrary string like ``"temperature"``
    is a plan defect — it would fail at execution. Coercible values (numeric
    strings for ``number``, boolean-ish strings for ``boolean``) and
    unresolved placeholders (``${...}``) are NOT violations. No schema →
    nothing reported (never guesses).
    """
    if not op or not isinstance(inputs, dict) or not inputs:
        return []
    meta = _capability_meta(op)
    schema = meta.get("input_schema")
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict) or not props:
        return []
    violations: list[tuple[str, Any, str]] = []
    for key, value in inputs.items():
        prop = props.get(key)
        if not isinstance(prop, dict):
            continue
        declared = prop.get("type")
        if not declared:
            continue
        if isinstance(value, str) and "${" in value:
            continue  # unresolved dataflow placeholder
        if isinstance(value, str) and _is_chain_expression(value):
            continue  # declarative producer-chain expression (RESOLVE(...))
        if declared == "boolean":
            if isinstance(value, bool):
                continue
            if isinstance(value, str) and value.strip().lower() in (
                "true", "false", "1", "0", "yes", "no",
            ):
                continue
            violations.append((key, value, declared))
        elif declared in ("number", "integer"):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                continue
            if isinstance(value, str):
                try:
                    float(value.strip())
                    continue
                except (ValueError, TypeError):
                    pass
            violations.append((key, value, declared))
        elif declared == "string":
            if isinstance(value, str):
                continue
            if isinstance(value, (int, float, bool)) and value is not None:
                continue  # executor stringifies scalars
            violations.append((key, value, declared))
    return violations


def _estimate_cost(nodes: list[dict[str, Any]]) -> float:
    """Sum of per-op cost metadata (0 when unavailable — never guesses)."""
    try:
        providers = getattr(_gc_mod.get_global_context(), "capability_providers", {}) or {}
    except Exception:
        providers = {}
    total = 0.0
    for node in nodes:
        op = str(node.get("op") or "")
        for prov in (providers.get(op) or []):
            total += float(prov.get("cost_per_call") or 0.0)
    return total


def _requires_approval(op: str) -> bool:
    meta = _capability_meta(op)
    if not meta:
        return False
    return bool(meta.get("requires_approval")) or str(meta.get("risk_level")) in ("high", "medium")
