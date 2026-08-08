# Nexus Agent — Roadmap (Master Implementation Plan)

The evolution of Nexus from a LangGraph project into an **Agent Orchestration
Runtime**. Every phase is independently shippable, keeps the full test suite
green (baseline: 251 backend / 20 frontend), and preserves registered tools and
DB data.

**Guiding principles** (see
[engineering-principles.md](engineering-principles.md) + 
[runtime-contract.md](runtime-contract.md)): no hardcoding, everything
metadata-driven, typed contracts at every boundary, deterministic layers around
probabilistic planning, side-effect-free pure cores, and the invariant chain —
LLM proposes, registry resolves, validator verifies, compiler decides, executor
performs, artifacts prove, recovery handles, response only claims what
artifacts prove, memory remembers with provenance.

---

## Completed (2026-08-08) ✅

- **Stabilization (W1–W4)**: quorum graceful FAIL, `/state` fix, dead nodes
  removed (19-node graph), Aggregator reduces on SUCCESS, typed-status
  recovery, node-contract registry + drift tests, OTel spans.
- **Handoff repair**: the `_deep_freeze` scalar bug (the every-domain all-None
  artifact root cause), normalization state machine, artifact contract
  validation, cache-key unification, execution→artifact invariants,
  data-incorporation + per-artifact response coverage guards, memory
  reinforcement gate.
- **Architecture versioning (ADR 0008)**: `architecture.py` manifest — the
  single cache-key fingerprint across all caches, telemetry, and CI.
- **P4 (planner quality)**: IntentDetector (Tier-1 deterministic) + Tier-2 LLM
  decomposer; PlanValidator coverage / alignment / parameter-provenance /
  traceability rules; empty-plan policy; bounded repair with partial-execution
  fallback; `RESOLVE(...)` producer-chain synthesis; replan cache-bypass.
- **P0 (correctness + security)**: ReasoningBudget (unified replan counter,
  wall-time/graph-step/LLM/tool enforcement), cancellation terminal states +
  the `uncertain` outcome, idempotency keys, authorization gate, SSRF
  hardening, approval semantic binding, prompt-injection boundary, memory
  provenance + freshness.
- **P2 (quality)**: reproducibility record, adversarial test suite, response
  coverage metric, scenario tiers + stability score, 251 deterministic tests.

## Remaining tracks

- Durable background-job model (ExecutionRequest → Durable Job → Queue →
  Worker → Checkpoint → ArtifactStore — not `asyncio.create_task`).
- Tenant isolation (multi-tenant authorization).
- Full causal correlation-ID chain (invocation_id → intent_id → plan_id →
  execution_id → artifact_id → response_id) on every event.
- Performance optimization driven by the benchmark baseline
  (`scripts/benchmark.py`; the fingerprint-attributable baseline exists).

---

## Phase 0 — Runtime Contract (docs) ✅ current

- [runtime-contract.md](runtime-contract.md) — invariants, contracts map,
  side-effect rules, enforcement gates
- [roadmap.md](roadmap.md) — this document
- [architecture.md](architecture.md) — rewritten to the current runtime
- Documentation restructure: stale docs removed/updated, docs index added

## Phase 1 — Capability Resolution (`ResolutionEngine`)

Single source of truth for "what is relevant". One frozen `ResolutionResult`
consumed by router (binary facts), planner (ranked candidates), and telemetry
(explanation).

- `resolution_result.py` — frozen models: `CandidateBase` (id, name, score,
  confidence, `match_sources`, reasons) → `CapabilityCandidate` +
  `WorkflowCandidate`; `ResolutionMetadata` (elapsed_ms, catalog_size,
  fingerprint, registry_version, layers_run, resolver_version); `ResolutionResult`
  (both candidate streams, `has_*_candidates` facts, metadata, explanation)
- `resolution_engine.py` — capability stream (existing retriever layers with
  multi-source reasons) + workflow stream (`template_engine`) +
  `ConfidenceClassifier` (Phase 1: score bands; Phase 6: multi-factor)
- **Availability facts**: `availability` on `CapabilityCandidate`
  (available/unavailable/disabled/rate_limited/maintenance/permission_denied)
  + the missing `enabled` filter in `with_tool_metadata`
- Router consumes facts only (no score thresholds); planner gets ranked
  candidates; debug endpoint returns `ResolutionResult`
- `registry_version` (int) distinct from content-hash `fingerprint`

## Phase 2 — ExecutionGoal Taxonomy

Replace query-type thinking with composable goal flags.

- `ExecutionGoal` flag set `{conversation, information, analysis, action,
  workflow}` + `primary_goal` (deterministic priority) + `needs_requirements`
  as a modifier — no more tool-count taxonomy
- Legacy alias map for persisted checkpoints (`"single_tool" → "action"`, …)
- Typed `GoalClassification` result; `response_type` becomes a typed enum

## Phase 3 — Plan Validator (pre-compile)

Deterministic safety layer between planner and compiler.

- `PlanValidatorNode`: undefined ops, cycles, missing inputs
  (`find_unmet_inputs`), schema mismatch, budget, policy/permission
- Typed `PlanValidatorReport`; routes: valid → Compiler, structural →
  RequirementCollector, refinable → PlanCritic

## Phase 4 — Execution Policies + Strategy + Enriched Plan

Execution behavior becomes declarative.

- `execution_policy` block: timeout_s, retries, parallel, risk,
  requires_approval, idempotent, cacheable, budget_usd, permissions, rollback
  (back-compat readers)
- Availability **policy** (maintenance windows) alongside Phase 1 facts
- `ExecutionStrategy` (sequential/parallel/map/reduce/retry/background/
  streaming) between planner and compiler
- Enriched `ExecutionPlan`: goal, nodes, dependencies, policies,
  estimated_cost, **estimated_latency_ms**, expected outputs, required
  approvals, failure recovery; background-vs-inline decision via
  settings-driven `background_threshold_ms`

## Phase 5 — Memory Lifecycle

Memory participates in planning and execution, not just response.

- `MemoryScout` `TRIGGER_PLANNING` → typed `MemoryRetrievalResult` injected
  into planner prompt/catalog (bounded)
- Executor cacheable artifact reads (long-term, keyed by `execution_key`),
  write-back on success

## Phase 6 — Semantic Workflow Matching

Hybrid discovery quality on top of RapidFuzz.

- `embedding` vector column on `workflow_definition` + backfill (LLMClient.embed)
- Hybrid scoring: vector cosine + token_set_ratio + metadata boost, fuzzy-only
  fallback
- `ConfidenceClassifier` multi-factor upgrade; resolver "embedding" source goes live

## Phase 7 — Observability

- Typed event models replacing `AgentEvent.payload: dict` (one model per event
  type)
- Per-node cost/latency/retries/decision-reason attributes; `ResolutionResult`
  surfaced in `/debug` + LangSmith tags

## Phase 8 — Artifact Registry

- DB-backed artifact registry: schemas, versions, relationships, ownership,
  lifecycle; in-session `ArtifactGraph` becomes a view over it

## Phase 9 — Executable + Execution Contract

- `ExecutionContract` implemented by every executable; `ResolutionResult`
  unifies candidate streams (`executable_candidates`); `ExecutionContext`
  enrichment (checkpoints/permissions/budget) migrates here

---

## Execution order

```
0  Runtime Contract          ← done
1  Capability Resolution     ← next
2  ExecutionGoal flags
3  Plan Validator
4  Policies + Strategy + Enriched Plan
5  Memory lifecycle
6  Semantic workflow matching
7  Observability
8  Artifact Registry
9  Executable + Execution Contract
```

Phases 1–4 hard-order; 5–8 swappable; 9 last. Every phase ends with: typed
contract tests, purity tests, boundary grep gate, full suite + E2E green.
