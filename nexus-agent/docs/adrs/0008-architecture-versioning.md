# ADR 0008 — Architecture Versioning & Migration Policy

*Status: ACCEPTED (2026-08-07). Supersedes scattered version constants.*

## Context

The orchestration layer is a frozen internal platform (ADR 0007). Cache
keys, telemetry, diagnostics, and benchmarks previously referenced
scattered version constants (`ARTIFACT_SCHEMA_VERSION`, `NORMALIZER_VERSION`,
`COMPILER_VERSION`, an inline renderer hash) — they could drift apart and a
stale cache could silently serve data produced by older architecture code
(the poisoned-artifact incident of 2026-08-07).

## Decision

`src/nexus/agent/architecture.py` is the **single runtime source of truth**
for architecture versions:

| Component | Source | Current |
|---|---|---|
| `orchestration_api` | graph topology + routing + state ownership (ADR 0007) | 1 |
| `artifact_schema` | `ARTIFACT_SCHEMA_VERSION` (ArtifactBase payload contract) | 1.0 |
| `normalizer` | `NORMALIZER_VERSION` (RAW→NORMALIZED contract) | 2 |
| `node_contract_schema` | node-contract registry shape (contracts.py) | 1 |
| `execution_graph_schema` | `COMPILER_VERSION` (ExecutionGraph IR + codegen) | 2 |
| `renderer_contract` | ArtifactRenderer base contract | 1 |

API:

- `ArchitectureVersion.current()` — runtime/API use (deep-copied manifest).
- `ArchitectureVersion.cache_fingerprint()` — SHA256 over the manifest;
  **the only** architecture version in cache keys.
- `ArchitectureVersion.to_json()` — telemetry/diagnostics/CI artifacts.
- `ArchitectureVersion.get(component)` — single-component lookup.

Rules:

1. **Breaking changes bump the manifest** — graph topology/routing/state
   ownership, artifact payload contract, normalizer contract, node-contract
   registry shape, ExecutionGraph IR/codegen contract, renderer base
   contract. Bumping any value changes `cache_fingerprint()` and invalidates
   every architecture-versioned cache (parse, plan, tool-result,
   normalized-artifact).
2. **No scattered constants in cache logic** — cache keys embed
   `cache_fingerprint()` only (enforced by `test_cache_keys_embed_fingerprint`).
3. **Drift is impossible** — `tests/test_architecture_versions.py` asserts
   the manifest matches its source constants and that the fingerprint is
   sensitive to every component.
4. **Migration notes** — every bump adds a dated note to this ADR and
   re-runs the baseline regeneration: full deterministic suite + handoff
   gate + scenario matrix under the new fingerprint.
5. **Exposure** — the fingerprint rides on every `InvocationOutcome`, the
   benchmark report header, and the `artifacts/architecture-fingerprint.json`
   CI artifact — any run is attributable to the exact architecture version
   that produced it.

## Migration notes

- 2026-08-07: initial manifest (`91d362e7a3dffb8e`). No component changes —
  consolidation only (scattered constants read through the manifest).
- 2026-08-07: exposure complete — the fingerprint rides on every
  `InvocationOutcome`, the benchmark report header, and
  `artifacts/architecture-fingerprint.json`. Phase-5 scenario governance
  added: per-scenario `tier: fast|medium|full` metadata, `--tier`
  filtering in `tests/run_scenarios.py`, and the Scenario Stability
  Score (`scripts/stability_score.py`, health = ≥3 consecutive clean
  runs). Fast tier (25 canonical scenarios) runs in the CI gate; medium
  nightly; full before releases.
- 2026-08-08 (P0 hardening): parameter provenance + capability alignment
  rules, response coverage, ReasoningBudget (`_invocation_budget` — the
  unified replan counter), SSRF hardening (`enforce_ssrf` for the
  dynamic-endpoint class), and the deterministic `RESOLVE(...)`
  producer-chain synthesis in the compiler. Planner prompt measured to
  v2.4 (the six-example v2.5 regressed the fast model — examples reverted,
  the intent-unit rule retained).
- 2026-08-08 (all-phases closure): budget-flow completion (executor ledger
  + response LLM consumption), idempotency keys (stable across retries,
  `validation_rules.idempotency_header` stamping), cancellation terminal
  states (`_invocation_status`; the `uncertain` outcome never retried),
  authorization gate (`validation_rules.allowed_roles`), approval semantic
  binding (`operation_hash` — modified steps never auto-authorized),
  prompt-injection boundary (finalize v4.1), memory provenance +
  freshness (`observed_at`/`source`/`scope`/`confidence` + `expires_at`
  via `ttl_s`), reproducibility record, `_response_coverage` metric, and
  the adversarial test suite. Finalize prompt v4.1; logical_planner v2.4.
