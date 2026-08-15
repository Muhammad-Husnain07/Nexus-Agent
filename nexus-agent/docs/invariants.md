# Runtime Invariant Ledger (binding rulebook)

Status per stage. GREEN = implemented and passing; PENDING = intentionally
not implemented yet (stage listed); RED = implemented but failing; PARTIAL =
partially enforced (stages listed). Tests live in `tests/test_invariants.py`
(one class per invariant). A stage gate requires: all invariants GREEN or
PARTIAL for stages completed so far are green; PENDING invariants never
block the current stage.

| ID | Invariant | Status | Enforcement point |
|----|-----------|--------|-------------------|
| I1 | No unresolved `RESOLVE(...)` crosses the compiler → executor boundary. | GREEN (P0-A) | `compiler/codegen.py` `_synthesize_resolve_producers` raises `CompilerError` on any unresolvable chain expression; bounded replan via `compiler_node.py`. |
| I2 | No unresolved placeholder (`${ref.result...}`) reaches a tool. Never `None`, never the raw string. | GREEN (P0-A) | `agent/executors/concurrent_executor.py` `_resolve_placeholder_value` raises `PlaceholderResolutionError`. |
| I3 | Action/executable intent + no executable plan + no artifacts can never produce a knowledge answer. | GREEN (P0-A) | `agent/nodes/response.py` `response_node` — executable-intent guard before the pure-chat path. |
| I4 | Every executable intent has explicit per-intent coverage evidence (capability alignment included). | GREEN (P0-B, B3 landed) | `agent/nodes/plan_validator_node.py` — per-unit evidence in `metrics.intent_coverage_evidence` (unit, candidates, planned matches, best, chosen, engine_top, engine_dominant, engine_verdict, aligned, served). FINAL B3 SEMANTICS: alignment verdicts come from the deterministic resolver's per-unit SCORES (aligned / misaligned / ambiguous / no_signal); `misaligned` (pick differs from the engine top AND evidence STRONG — 2x dominance or unique >= 5.0) is ERROR/REFINE blocking; `ambiguous` is evidence-only, NEVER blocking (the historical false positives — scenarios 8/20/38/47 — lived in weak/close-signal territory). LOCKED RULE: alignment blocking may only use deterministic resolver evidence for the specific intent unit; lexical/keyword similarity must never independently cause an execution-blocking decision. |
| I5 | Non-idempotent side effects carry durable operation identity (attempt_id never participates in dedup). | GREEN (P0-D/D1) | `execution/ledger.py` — `completed_executions` table, PK (session_id, execution_key = SHA256(tool + resolved inputs)); atomic claim + lease; completed results replayed, never re-executed; definite failures release the lease; `uncertain` never releases (lease expiry prevents duplicates). |
| I6 | A terminal checkpoint cannot silently resume. | GREEN (P0-D/D2) | `agent/runner.py` — terminal-abnormal markers (CANCELLED/TIMED_OUT/INTERRUPTED/FAILED) persisted to the checkpoint with pending-graph reset (`as_node="__start__"`); invoke() refuses stale-graph continuation; `api/chat.py` `derive_run_status` reports terminal statuses truthfully. |
| I7 | `cache_scope != public` ⇒ cache lookup MUST carry authenticated scope, centrally enforced. | GREEN (P1-A/A2) | `memory/store.py` `find_by_metadata(session_scope=...)` — the artifact-cache read paths (raw + normalized) pass the session scope; only capabilities explicitly declaring `validation_rules.cache_scope == "public"` (operator-approved) are exempt. Default = private. |
| I8 | Approval is bound to the exact approved operation (hash enforced on every grant path). | GREEN (P0-C) | `agent/nodes/multi_approval_gate_node.py` — hash over policy(+version) + step + tools + step inputs + RESOLVED tool inputs + capability ids + graph version; enforced on BOTH grant paths (global + per-step); `_approval_decision` consumed after grant; resume node records `step_{id}_decision` + `step_{id}_hash`. |
| I9 | Untrusted tool/memory/web data cannot become instructions. PARTIAL: fail-closed prompt resolution (no silent fallback, registered versions only) enforced in P0-A; the full prompt-boundary work lands in P0-B (planner history/memory boundary) and P2 (finalize boundary headers, sanitization). | PARTIAL — P0-A, complete P0-B/P2 | P0-A: `prompts/manager.py` `PromptVersionError`; every `prompt_manager.render` call site uses a registered version (drift test). |
| I10 | Every execution has reproducible identity/versions persisted. | GREEN (P2-B) | `invocation_outcomes` request_id/agent_run_id/temperature/seed/registry_fingerprint/planner_metrics/intent_coverage/reproducibility/prompt fingerprints + logical refs (SHA256 references, never blobs); dataclass/INSERT/model/migration parity tests (`tests/test_reproducibility_p2b.py`). |
| I11 | Invalid plans cannot be cached or executed. | GREEN (P0-D/D0, extended P1-A) | `agent/nodes/plan_validator_node.py` `unknown_input_key` rule (ERROR/REFINE); `semantic_parser_node._plan_unsafe_to_cache` guards ParseCache WRITE + READ (schema-invalid values, missing required inputs, invented keys, AND unprovable REQUIRED-input literals — the scenario-35 value-provenance replay class, added in P1-A); `compiler_node._graph_has_unknown_input_keys` re-checks PlanCache hits (invalid cached graphs are recompiled, never executed). |
| I12 | Non-idempotent operations are never automatically retried across outcome uncertainty unless explicitly permitted by capability failure semantics. | GREEN (P1-A/A0) | `agent/executors/concurrent_executor.py` — retry loops + endpoint fallback bound by the idempotency-scoped `task_retries` (0 for non-idempotent); `tools/mcp_client.py` — MCP transport retries disabled for non-idempotent tools. Recovery-layer reflection retries remain gated by `max_reflection_retries` (M7 `failure_semantics` design is the follow-up). |
| I13 | A plan may persist in the parse cache only when semantically cache-eligible; REFINE/ABORT/partial plans never persist. | GREEN (P2F) | The planner's write is structurally gated (`_plan_unsafe_to_cache` — schema/provenance, I11); the VALIDATOR is the semantic gatekeeper (`plan_validator_node._remove_semantically_ineligible_plan`) — any verdict that is not eligible (report invalid, or coverage < 100%, or a capability_alignment violation) removes the entry; the COMPILER removes the entry on compile failure. Reads are revalidated by the validator after every cache hit (a rejected cached entry is removed — pre-rule entries self-heal on first rejection). Cache-eligibility is a property of the PLAN's semantics (validator verdict + compile success), never of execution outcomes. |
| I14 | Every executable intent must retain at least one viable capability path (branch-safe coverage invariant). | GREEN (P0-A.3 / P0-C) | `capabilities/capability_semantics.py` `branch_safe_select` — per-intent (branch-local) ranking/suppression/marginal-cut; the distinctness invariant re-admits a branch's only viable capability when its survivors are all copies of other branches' picks (K83's `reverse_geocode` survives a 100:2 raw-score domination). |
| I15 | Resolver evidence must not silently override a correct deterministic pick (alignment verdict = same semantics as the resolver). | GREEN (P0-D.1) | `plan_validator_node._semantic_filter_engine` + `_ALIGNMENT_DOMINANCE_FLOOR` — generic-suppressed engine scores feed the alignment verdict; keyword-noise ratios never block; explicit web requests keep the generic fallback. |
| I16 | An executable request that produces no artifacts/errors must never be answered as silent success. | GREEN (P1-B, PH-1) | `response_node` `_response_status` machine — `PLANNING_FAILED` / `EXECUTION_FAILED` explicit terminal statuses; never "I processed your request." PH-1 made the machine TOTAL (every exit stamps; `CONVERSATIONAL` for pure-chat) and fixed the checkpoint lie: a budget-exceeded invocation now persists `TIMED_OUT`/`INTERRUPTED` monotonically (never downgraded to `COMPLETED` — runner regression-tested). |
| I17 | A node's required input with NO resolvable source (binder-classified) must not void valid branches on a multi-node plan. | GREEN (P1-A / P2-A) | `ViolationAction.DROP_AND_PROCEED` — unresolvable-input nodes drop (partial success), including mixed unresolvable+alignment verdicts (reviewer L5); the mega-DAG never wall-time-kills a 20+ node plan for one missing docker `repository`. |
| I18 | A dangling MapNode (iterate_over without a declared collection) must never fail validation and burn a replan cycle — and a lost fan-out is never invisible. | GREEN (P2-A.2, PH-5) | `semantic_parser_node._strip_dangling_maps` — strips `iterate_over` (single-body degradation) AND records `_map_degradations` (node/iterate_over/reason); PH-5 surfaced the ledger as a `map_degraded` SSE event — the degradation is observable end-to-end. |
| I19 | Chunked (hierarchical) mega-DAG planning must not lose intent coverage across chunks. | GREEN (P2-A.1) | `_chunked_plan_extract` coverage invariant at the merge — units the chunk model skips are recovered deterministically via the hyphen-normalized engine resolve (top available capability added as a node). |

Rules of engagement (binding):

1. No unresolved symbolic reference crosses the compiler/executor boundary.
2. No silent fallback for missing production prompts — a missing prompt is a
   typed configuration error (`PromptVersionError`).
3. No terminal checkpoint continuation without explicit resume.
4. No retry of `uncertain` outcomes unless capability metadata explicitly
   permits it (P0-D).
5. Every stage lands fully green (invariant ledger + deterministic suite +
   scenario fast tier 3x) before the next stage starts.
6. Model config changes are isolated experiments (MODEL-AB-01) — the
   orchestration architecture is frozen; planner/synthesis model and
   embeddings are the only post-freeze variables.

## Cache dependency table (P1-B.2 — component-specific fingerprints)

```
Cache                 Depends on
-----------------------------------------------------------
ParseCache            planner prompt + registry
PlanCache             planner prompt + registry
ResolutionCache       registry
ArtifactResultCache   registry + capability schema + scope
ResponseCache         response prompt + artifacts
```

Invariant: a response (finalize) or router prompt change NEVER invalidates
parse/plan caches; a planner prompt change invalidates them; an artifact
cache row is never reused after its registry/schema contract changes.
