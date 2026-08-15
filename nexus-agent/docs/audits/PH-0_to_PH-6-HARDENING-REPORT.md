# Nexus Production Hardening — PH-0 .. PH-6 (2026-08-16)

Independent post-audit hardening phase. The pre-hardening snapshot is
[NEXUS_COMPLETE_PROJECT_AUDIT-2026-08-16.txt](NEXUS_COMPLETE_PROJECT_AUDIT-2026-08-16.txt)
(immutable — do not edit it; it records the state at commit `1cce159`).

Architecture decisions from the review: the 19-node orchestration surface
(resolver semantics, binder, validator, map semantics, chunk merge/coverage,
evidence architecture, idempotency ledger, Ultra+Ultra model config,
embeddings OFF) was NOT reopened. Every change below is additive hardening,
deployment/config, observability, or documentation.

## PH-0 — Deployment/security blocker (commit `c220805`)

- k8s ConfigMap: `NEXUS_TOOLS__SANDBOX_ENABLED=false -> true`; wildcard
  `ALLOWED_HOSTS` replaced by the explicit 27-host allowlist of the
  registered tool hosts; model config aligned (Nemotron-3-Ultra planner +
  synthesis, `NEXUS_RESOLVER__ENABLE_EMBEDDING_RETRIEVAL=false`); dead knobs
  removed (`TEMPERATURE`, `MAX_TOKENS`, `MAX_ITERATIONS`, `MAX_PLAN_STEPS`,
  `CONTEXT_WINDOW_TOKENS`, `HITL_DEFAULT`, `SERVER_*`); header marks the
  ConfigMap authoritative vs developer `.env`.
- secret.yaml: `CHANGE_ME` documented as required; NIM key + auth-key
  placeholders.
- Local `.env` (root + nexus-agent, gitignored): wildcard removed, same
  explicit allowlist, `SANDBOX_ENABLED=true` (root `.env` was `false`).

## PH-1 — Correct runtime state (commit `c220805`)

- Runner terminal-marker fix: budget-exceeded `TIMED_OUT`/`INTERRUPTED` was
  written to `initial_state` and then overwritten by `COMPLETED` in the
  finalization (`runner.py`). Now written to `_last_state` (the persisted
  state), finalization is monotonic (terminal-abnormal is never downgraded,
  persisted immediately, pending graph reset via `as_node="__start__"`), and
  `final_status` reflects the marker. Regression tests: fake-graph runner
  test (budget exceeded -> checkpoint `TIMED_OUT`, never `COMPLETED`;
  normal path still `COMPLETED`).
- `_response_status` machine is now TOTAL: every `response_node` exit stamps
  a status (new `CONVERSATIONAL` for pure-chat; passthrough preserves prior;
  compile failure / LLM-budget-exhausted / LLM-failed / degenerate /
  conversational-failure -> `EXECUTION_FAILED`; structured passthrough ->
  `SUCCESS`). AST totality guard test catches any future unstamped return.
  Also fixed a pre-existing broken test fake (unbound `complete()` made the
  conversational-success test pass vacuously through the exception path).

## PH-2 — Evidence correctness (commit `a237950`)

- Evidence compilation fails CLOSED: exception -> `(None, None)` sentinel
  (logged ERROR), never silently-empty evidence; response treats it as
  `EVIDENCE_COMPILATION_FAILED`: coverage 0.0, `PARTIAL_SUCCESS`, breakdown
  `evidence_available < evidence_required` (required = artifact count).
- `hallucinated_evidence` now invalidates `GroundingCoverage.complete` even
  at full ratio, and drives the gate -> one repair -> deterministic renderer.
- Grounding-check exceptions (validator returns None) also fail closed to
  coverage 0.0 instead of defaulting to 1.0.
- `_synthesis_fallback_patch` sentinel-safe. Tests: Class A (compile
  exception sentinel + response-level coverage 0.0/PARTIAL), Class C
  (hallucination at ratio 1.0 -> not complete).

## PH-3 — Approval lifecycle + background deployability (commit `8d3bd62`)

- `agent.approval_expiry_s` (default 3600s): pending approvals expire on
  resume ("approval request has expired — nothing was executed"); operation
  hash covers content drift, expiry covers time drift.
- `_checkpoint_denied_tools` reads the LIVE `_approval_pending` (the legacy
  `_approval_checkpoint` was never written — the denied set was always empty
  and the reject-blocks-graph replan rule was dead); legacy key kept as
  fallback.
- `deploy/k8s/worker.yaml` + `scheduler.yaml`: first-class worker and
  scheduler Deployments (previously background tasks queued forever unless
  an operator ran `python -m nexus.tasks`).
- `/tasks` API tenant scoping: session-bound tasks addressable only by the
  session owner (403 otherwise); session-less operator/system tasks stay
  open; create validates the originating session; list filters.

## PH-4 — Reproducibility + CI (commit `51e46e3`)

- `nexus-agent/benchmarks/frozen_baseline/`: the 3x Ultra+Ultra 135-scenario
  runs (verified 98/135 each; avg 91.3 / 91.5 / 90.6; mean 91.1), the
  P2-A.6 gate run (7/7, 99.3 — C36 95 flake), the post-P3 gate run (7/7,
  100.0), and `summary.json` (model, scorer, weights, dimension means —
  values verified against the artifacts, not copied from docs). Supersedes
  the stale root `benchmark_report.json` (83/135, 2026-08-12 — removed in
  PH-6B).
- Root CI: backend `pytest -m "not live"` (live suites need NIM + servers
  and previously failed deterministically on runners); broken frontend steps
  removed (no `typecheck` script; vitest/jsdom undeclared); timeouts added;
  nightly job for the live benchmark. The nested
  `nexus-agent/.github/workflows/ci.yml` never executes (GitHub only reads
  root workflows) — removed in PH-6B.

## PH-5 — Observability (commit `23b44a8`)

- `_map_degradations` (P2-A.2) surfaces as a `map_degraded` SSE event
  (node/iterate_over/reason) — a stripped fan-out is now observable
  end-to-end; empty ledger emits nothing.

## PH-6A — Observability, continued (commit `66e70b4`)

- Planner latency persisted (`_planner_latency_ms` — was accepted by
  `_build_patch` and never written).
- Mega-DAG chunk timing persisted (`_planner_chunk_timing`: chunk_count /
  sizes / start_order / partition / rotation / concurrency / per_chunk_ms /
  max / sum) via a `chunk_timing_meta` payload that is popped out of the
  strict-schema workflow before it enters the state.
- Branch-safe resolution suppressions surfaced (`_resolution_suppressions`:
  capability -> reason, bounded) and emitted as `resolution_suppressed`.
- SSE events `planner_timing` + `resolution_suppressed` from the planner
  update; new state channels registered in `AgentState` /
  `_EPHEMERAL_FIELDS` / node contract (drift tests green).

## PH-6B — Cleanup / documentation (this commit)

- Dead code removed (verified zero callers): `route_after_estimator`,
  legacy `approval_gate_node` (graph.py), `invalidate_all_caches()` +
  `ParseCache.invalidate` (compiler/cache.py),
  `compiled_graph.invalidate_cache()`, `RegistryClient.clear_cache()`,
  duplicated `registry_version()` (second def), `template_engine._fuzzy_match`,
  dead node modules `cron_node.py` / `clarification_node.py` / `finalize.py`
  + their `nodes/__init__.py` exports, nested dead CI workflow, stale root
  `benchmark_report.json`.
- Stale test fixed: `test_b3_alignment` case6 asserted pre-P1-A ratio-only
  dominance; the frozen P1-A semantics adds the 10.0 absolute floor
  (keyword-noise tops never block) — test now asserts the floor behavior
  (12.0 vs 3.0 -> misaligned; 7.0 vs 3.0 -> ambiguous).
- Docs reconciled: invariants I16/I18 rows updated (PH-1/PH-5 closures);
  README claims fixed (React Router v7, no recharts, real performance
  table, benchmark pointer to `benchmarks/frozen_baseline/`, observability
  wording).
- Audit snapshot moved to `docs/audits/` (immutable; historical value).

## Acceptance (post-PH-6B)

- Targeted regression suites: invariants, validator, evidence, approval,
  tenant, worker, checkpoint, P1/P2 suites.
- Live scenario check on the frozen gates + mega-DAGs: C36 C40 C41 K82 K83
  D48 D49 T132 U133 W135 (orchestration health: planned/executed non-zero,
  no crashes; endpoint variance documented).
- 19-node topology unchanged (node-contract + architecture-version drift
  tests); no new lint/type errors; working tree clean.

## Deliberately NOT changed

Resolver semantics, IntentGraph, binder, validator alignment rules, map/
fan-out semantics, chunk merge/coverage, evidence architecture, execution
topology, idempotency ledger, recovery semantics, Ultra+Ultra model
selection, embeddings OFF, chunk knobs (P3 closed negative — endpoint-bound).
