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

- **P3-A/B: adaptive chunk balancing** — CLOSED (negative; see the P3
  section below — `max(chunk_latency)` is endpoint-latency-bound).
- Durable background-job model (ExecutionRequest → Durable Job → Queue →
  Worker → Checkpoint → ArtifactStore — not `asyncio.create_task`).
- Tenant isolation (multi-tenant authorization).
- Full causal correlation-ID chain (invocation_id → intent_id → plan_id →
  execution_id → artifact_id → response_id) on every event.
- `nv-embed-v1` re-evaluation when the registry grows substantially beyond
  22 tools (D10 verdict: no measured benefit at 22 tools — resolution 0.857
  ON = OFF).

---

## P3-A/B experiment (adaptive chunk balancing) — CLOSED, negative

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

### Result (W135, 15 runs, Aug 2026; knobs + instrumentation landed)

| Config | max(chunk_latency) samples | median |
|---|---|---|
| control (sequential, cs6) | 33.3, 66.5, 69.7, 77.4, 78.4, 87.7, 109.3, 115.4, 138.0 | ~87.7s |
| rotation (start order rotated; position-vs-content diagnostic) | 45.1, 69.1, 124.6 | ~69s |
| concurrency=2 (bounded in-flight chunk calls) | 68.4, 137.2 | ~103s |
| interleaved partition (unit i → chunk i mod k) | 48.4, 86.0, 154.7 | ~86s |
| chunk_size=4 (sequential) | 66.4, 192.3 | ~129s |
| chunk_size=4 (interleaved) | 103.7 | ~104s |

**Findings:**

1. **The tail is content-driven, not positional.** The rotation diagnostic
   is decisive: chunk 1 (W135 units 6–11: the reverse-geocode dependency
   + country summaries + anime cluster) was the slowest in 7/7 runs
   regardless of which start slot it occupied; chunk 2 was always fastest.
2. **No scheduling lever helps.** Rotation and bounded concurrency leave
   `max(chunk_latency)` inside the control distribution.
3. **No partition lever helps.** Interleaving spreads the hard region (one
   nicely-balanced run at 48.4s), but the penalty then migrates to random
   chunks: per-call endpoint variance (6–192s for identical content, 0
   instructor failures / 0 JSON fallbacks / 0 empty chunks in all 15 runs)
   is 3–5x larger than the content-imbalance effect being targeted.
4. **chunk_size=4 does not help** (more calls, same per-call variance).

**Conclusion: the P3 hypothesis is falsified.** `max(chunk_latency)` is
endpoint-latency-bound, not partition-bound; the P2-A.5 78.4s was itself the
median of a wide distribution. The instrumentation (settings knobs
`chunk_rotation` / `chunk_concurrency` / `chunk_partition`, `chunk_sizes` +
`start_order` fields on `semantic_planner.chunk_timing`, the interleaved
partition helper) is retained with defaults equal to the frozen control
behavior — zero behavior change when unset. Frozen gates verified after the
instrumentation landed: **7/7, avg 100.0**. Further mega-DAG wall-time work
would have to address the NIM endpoint itself (provider-side), which is out
of scope for orchestration code.
