# Nexus Agent — Roadmap (Master Implementation Plan)

The evolution of Nexus into an **Agent Orchestration Runtime**: deterministic
compiler-inspired orchestration around a probabilistic planning core. Every
phase keeps the deterministic test suite green and preserves registered tools
and DB data.

**Guiding principles** (see [engineering-principles.md](engineering-principles.md) +
[runtime-contract.md](runtime-contract.md)): no hardcoding, everything
metadata-driven, typed contracts at every boundary, deterministic layers around
probabilistic planning, side-effect-free pure cores, and the invariant chain —
LLM proposes, registry resolves, validator verifies, compiler decides, executor
performs, artifacts prove, recovery handles, response only claims what
artifacts prove, memory remembers with provenance.

> **Architecture status: FROZEN.** The orchestration architecture (P0–P2) is
> validated and frozen at commit `8656ead`. Only model configuration and
> benchmark instrumentation change post-freeze; any further performance work is
> a separate P3 experiment with its own A/B measurement.

---

## Completed phases ✅

### P0 — Correctness + Security (2026-08-08)

- ReasoningBudget (unified replan counter, wall-time/graph-step/LLM/tool
  enforcement), cancellation terminal states + the `uncertain` outcome,
  idempotency keys, authorization gate, SSRF hardening, approval semantic
  binding, prompt-injection boundary, memory provenance + freshness.

### P0-A — Deterministic Resolver (2026-08-12, committed `5dc23ce`)

- `CapabilitySemantics` (specificity / generic / fallback / domains / requires /
  produces), deterministic ranker with generic-fallback suppression, marginal
  cutoff, dependency closure (weather → geocode producer synthesis), alias
  multi-match, keyword-boost always runs, capability metadata curated in
  `validation_rules.semantics`.
- **P0-A.3 branch-safe resolution** (`4fb1cf2`): per-intent (branch-local)
  selection with the coverage invariant + removal diagnostics — a candidate
  belonging to one intent never disappears because another intent has a
  stronger top. Benchmark-gated contamination-free.

### P0-B — Deterministic Parameter + Provenance Binder (2026-08-12, `8ea44fb`)

- Layered binding: L1 user values / L2–L3 artifact-output (produces/consumes) /
  L4 type guard / L5 provenance-checked LLM fallback; entity-identity producer
  pairing (B3/B4 — Lahore ≠ Karachi); `BOUND / MISSING / AMBIGUOUS / INVALID`
  classification; schema-default override guard (the docker `namespace`
  class); cache-hit plans also bind. Gates B31/D47/C40/R119 = 100.

### P0-C — Structured Intent Decomposition + Coverage (2026-08-12, `da0c245`)

- `DetectedIntent` / `IntentGraph` IR (goals/entities/relationships — never
  tool names); adaptive compound-signal trigger (anaphoric chains fire the
  Tier-2 decomposer; simple queries cost zero); the intent graph feeds the
  resolver branches AND validator coverage (engine-rank classifiability);
  distinctness coverage invariant in `branch_safe_select` (K83's
  `reverse_geocode` survives the marginal cutoff); planning-event intent
  accounting (requested vs planned). K83 45→100, C-section green.

### P0-D — Artifact → Evidence → Synthesis (2026-08-12, `a339fb4` + `53595f2`)

- `EvidenceCompiler` (entity-anchored ResponseEvidence via P0-B identity +
  producer chains), `RequiredEvidenceCompiler`, `GroundingValidator`
  (required ⊆ available ⊆ rendered, hallucination detection), compact
  `RESPONSE_EVIDENCE` packet injected into synthesis, one-pass synthesis
  repair, entity-anchored deterministic renderer fallback. O101 80→100,
  R119→100.
- **P0-D.1 validator alignment semantics** (`e835838`): the alignment verdict
  consumes the same CapabilitySemantics as the resolver (generic-suppressed
  engine scores) — D49 72→100 stable.

### P1-A — Large-DAG Efficiency (2026-08-13, `7c64da6`)

- Per-wave duration instrumentation (WaveCompleted carries `duration_ms`;
  critical-path accounting); `DROP_AND_PROCEED` for binder-classified
  unresolvable inputs on multi-node plans (no full-LLM replan — V134
  231s→119s, 0→7 branches executed); alignment dominance absolute floor
  (keyword-noise never blocks); noise-floor intent classifiability.

### P1-B — Empty-plan Safety (2026-08-13, `7c64da6`)

- Explicit `_response_status` machine: `SUCCESS / PARTIAL_SUCCESS /
  EXECUTION_FAILED / PLANNING_FAILED` — an executable request that produces
  no artifacts/errors is an explicit failure, never "I processed your
  request." Status rides the final_response SSE event + state.

### P1-C — Bounded Nano Extraction Recovery (2026-08-13, `32a45c9`)

- Diagnosed failure classes (`EMPTY_PLAN / INVALID_SCHEMA / MODEL_TIMEOUT /
  LLM_ERROR`) — never a blind retry; ONE constrained repair prompt for
  EMPTY_PLAN (names the detected units + registered capabilities, output
  constrained to `valid_ops`), capped at one repair, then PLANNING_FAILED.

### P1-D — Map / Fan-out (2026-08-13, `16774f6`)

- Deterministic map-collapse pass: independent same-capability entity
  instances → ONE Map node + declared collection (D48: detected=4,
  planned=1 MAP, cardinality=3, executed=3, 1 wave, 100); collections flow
  workflow→executor fan-out; evidence anchors map-item artifacts to
  collection items.

### P2 — Remaining Failure Elimination (2026-08-14/15)

- **Benchmark contract classification** (`590b9ea`): `BENCHMARK_CONTRACT`
  fires only when a required input is a CHAINED ARTIFACT absent from the
  expected set (weather-only expectations no longer pollute RESOLUTION).
- **Synthesis-coverage measurement** (`1088624`): coverage_breakdown on all
  response paths — every analyzed ARTIFACT_GRAPH failure is Class B
  (available=required, rendered=0): EvidenceCompiler is not losing
  information; Nemotron generation omits entities.
- **Model A/B (MODEL-AB-01)**: Step 3.7 Flash + Ultra 550B probes; the
  `synthesis_model` override (Config D/E); renderer list display
  (books render numbered title-author, `867df0c`).
- **P2-A hierarchical mega-DAG planning** (`c7449dd` + `beec212` +
  `9d72a79` + `8656ead`): size-aware chunked planning
  (`max_single_pass_intents=12`, `chunk_size=6`) — 20+ intent requests plan
  per dependency-ordered chunk (parallel extraction, deterministic merge)
  instead of one doomed single-shot; coverage invariant at the merge
  (hyphen-normalized engine resolve); collections-persistence guard
  (`_strip_dangling_maps` — a stripped fan-out is never invisible via the
  `_map_degradations` ledger); per-chunk timing instrumentation.

### Production model configuration (frozen)

```
Planner   = nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b
Synthesis = nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b (NEXUS_LLM__SYNTHESIS_MODEL)
Embeddings= OFF (NEXUS_RESOLVER__ENABLE_EMBEDDING_RETRIEVAL=false)
```

### Benchmark baseline (frozen architecture, 135 scenarios)

| Config | Pass | Avg | Notes |
|---|---|---|---|
| Nano+Nano (Run 13) | 94/135 | 90.3 | empty-plan class (Nano planner) |
| Nano+Ultra (Run 14) | 95/135 | 89.7 | 5 llm_failed (Ultra endpoint under load) |
| **Ultra+Ultra (135×3)** | **98/135 × 3** | **91.1** | reproducible; binding 1.0; artifacts 0.788; grounding 0.763 |

Mega-DAG validation (P2-A): T132 0→7 executed; W135/U133/T132 all plan
completely (all expected kinds, 0 empty plans on clean reps); T132 3/3
stable; planning critical path = max(parallel chunk) = 78.4s (P2-A.5).

---

## Remaining tracks (post-freeze)

- **P3-A/B: adaptive chunk balancing** (independent performance experiment —
  the ONLY permitted orchestration-adjacent change; see contract below).
- Durable background-job model (ExecutionRequest → Durable Job → Queue →
  Worker → Checkpoint → ArtifactStore — not `asyncio.create_task`).
- Tenant isolation (multi-tenant authorization).
- Full causal correlation-ID chain (invocation_id → intent_id → plan_id →
  execution_id → artifact_id → response_id) on every event.
- `nv-embed-v1` re-evaluation when the registry grows substantially beyond
  22 tools (D10 verdict: no measured benefit at 22 tools — resolution 0.857
  ON = OFF).

---

## P3-A/B contract (adaptive chunk balancing)

**Status:** P3 is performance optimization ONLY. P0/P1/P2 are not reopened
unless a new regression or concrete production failure provides evidence.

**Control (P2-A.5 baseline):** 4 chunks planned in parallel — 18s / 23s /
35s / **78.4s (critical path)**. Planning wall = `max(chunk_latency)` = 78.4s
of the 180s budget (44%); merge ~0.1s. The key metric is **`max(chunk_latency)`**
(parallel execution), NOT the sum.

**Hypothesis:** adaptive partitioning → more balanced chunks →
lower `max(chunk_latency)` → more execution headroom → lower total wall time.

**P3 MAY change:** chunk size, partition strategy, scheduling.

**P3 MAY NOT change:** intent coverage, resolver semantics, binding, map
semantics, evidence/grounding, validation contracts, execution correctness.

**Experiment design:** P3-A vs P3-B on W135 (and T132/U133 when cold),
measured by `max(chunk_latency)` + benchmark deltas against the frozen
baseline; a change is adopted only if the 135-scenario aggregate and the
mega-DAG gates stay green (A/B, one variable at a time).
