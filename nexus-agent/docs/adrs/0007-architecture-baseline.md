# Architecture Baseline — Frozen Reference (Step 0)

*Status: FROZEN at 2026-08-07, before the handoff-repair work (Steps 1–7).*
This document snapshots the orchestration contracts that Steps 1–7 must
preserve. Any change that alters a frozen contract below requires an ADR +
regression-test update.

## 1. Node Graph (19 nodes, frozen)

```
RouterNode
  → ResponseNode (conversation/information/knowledge)
  → KnowledgeAssistant merged into ResponseNode (information goal)
  → RequirementCollectorNode (needs_requirements)
  → InteractiveWorkflowNode (active workflow / workflow goal)
  → ApprovalCheckpointResumeNode (open approval)
  → SemanticPlannerNode (action)
SemanticPlannerNode → PlanValidatorNode
PlanValidatorNode → {CompilerNode | RequirementCollectorNode | SemanticPlannerNode | END}
CompilerNode → {OptimizerNode | EstimatorNode}         (optimizer bypass ≤3 nodes / budget)
OptimizerNode → EstimatorNode
EstimatorNode → ValidationNode
ValidationNode → {ApprovalGateNode | ResponseNode | RequirementCollectorNode}
ApprovalGateNode → {ExecutorNode | ResponseNode}
ApprovalCheckpointResumeNode → {ApprovalGateNode | SemanticPlannerNode | ResponseNode}
ExecutorNode → {InteractiveWorkflowNode (workflow resume) | AggregatorNode | ResponseNode}
AggregatorNode → ValidatorNode (runs when ReduceNodes present or partial failure)
ValidatorNode → RecoveryManagerNode
RecoveryManagerNode → {ReflectionNode (retry) | ReplanNode (replan) | ResponseNode (fail)}
ReflectionNode → {ExecutorNode (retry) | ResponseNode (finalize)}
ReplanNode → SemanticPlannerNode
ResponseNode → MemoryHelperNode → END
```

Removed in W1 (dead): DecompositionNode, SelfHealingNode, PlanCriticNode,
KnowledgeAssistantNode.

## 2. State Ownership (frozen — enforced by tests/test_node_contracts.py)

Single owner per field (exceptions: shared channels `errors`, `messages`,
`final_response`, `response_type`, `working_memory`, `intent`, `tool_results`,
`iteration_count`, `total_cost_usd`, `_routing_decision`, approval-coordination
fields, `_logical_workflow` (planner + workflow node), `_total_retry_count` /
`_recovery_*` (recovery + reflection), `_route_to_planner`, `_ready_to_plan`,
`_replan_context`, `_bypass_workflow`, `_structured_payload`).

Canonical execution graph: `_execution_graph` (+ `_graph_version`,
`_optimization_snapshots`). Compile-phase: planner/validator/compiler/
optimizer/estimator/validation. Runtime-phase: gate/executor/aggregator/
validator-post/recovery/reflection/replan/response/memory/workflow.
Routing-phase: router/approval-resume/requirement-collector.

## 3. Artifact Contracts (frozen — the subject of Steps 1–5)

- Pipeline: RAW_TOOL_RESULT → normalize_artifact (projection + x-artifact-fields
  deep flatten) → ArtifactBase (frozen, content_hash of normalized payload) →
  ArtifactGraph (session) + ArtifactRegistry (durable DB, best-effort) +
  normalized-artifact cache (kind="normalized_artifact", keyed by execution_key).
- `x-artifact-fields` declared on 13 tools (geocode, weather, docker, meals,
  anime, manga, country, books, authors, reverse-geocode, universities,
  exchange, dictionary).
- ResponseNode consumes ONLY the ArtifactGraph (never tool_results).
- Invariant: successful execution + artifacts ⇒ never `response_type="error"`.

## 4. Execution Pipeline (frozen)

Wave-based ConcurrentExecutor; typed statuses (success/error/validation_error/
timeout/rate_limited/unavailable/tool_not_found); placeholder dataflow;
idempotency keys; endpoint fallback; schema coercion; `_execution_events`
(bounded 50); `_stage_metrics` (node → ms, inter-event delta attribution).

## 5. Response Pipeline (frozen)

ResponseNode: conversational fast-path → workflow structured passthrough →
ContextIR (_compile_and_render) → CompilerPipeline (PromptCache) →
PromptRenderer (progressive) → LLM finalize → structural degenerate guard →
Artifact Renderer fallback (_render_artifacts) → persist_after_response
(working memory). Budget degradation: `_budget_exceeded` → renderer.

## 6. Memory Pipeline (frozen)

MemoryHelperNode (gated to tool turns): ArtifactGraph facts →
MemoryManager.extract_and_store (LLM extraction + EpisodicSummarizer) →
pgvector; artifact memories (kind="artifact_memory", dedup by
(artifact_type, content_hash, schema_version)); MemoryScout.scout_for_planning
(semantic + artifact memories via shared store); persist_after_response →
working_memory.last_response.

## 7. Cache Keys (frozen)

ParseCache: query+model+context+COMPILER_VERSION+ARTIFACT_SCHEMA_VERSION+
registry fingerprint. PlanCache (compiled graphs): logical-workflow hash +
versions + fingerprint. Tool-result cache: kind="artifact", execution_key
(input-based). Normalized-artifact cache: kind="normalized_artifact",
execution_key. Artifact dedup: (artifact_type, content_hash, schema_version).

## 8. Execution Invariants (frozen — Steps 1–5 harden these)

1. `normalize_artifact` is deterministic and must never run on an already
   normalized payload.
2. A declared `x-artifact-fields` path must resolve to a non-None value
   (or be declared `x-artifact-optional`); silent all-None artifacts are
   prohibited.
3. Executor SUCCESS outcomes must produce registered artifacts (count/validity
   checked post-execution).
4. Compile-phase nodes never write runtime-owned fields (contract test).
5. Planner completeness: consumers without producers (missing_producer) and
   producers without consumers (missing_consumer) are REFINE violations.

## 9. Step 1–7 Contract Amendments (2026-08-07, applied after freeze)

1. **Deep-freeze scalar pass-through** (THE handoff root cause): the missing
   base case in `_deep_freeze` returned `None` for every scalar — every
   registered artifact had all values nulled while the executor's event data
   stayed real. `ArtifactBase` now preserves scalars; regression-tested.
2. **Normalization state machine**: `RAW_TOOL_RESULT → NORMALIZED (marked
   `_nx_state`) → REGISTERED (stripped)`. `normalize_artifact` raises on a
   marked payload; the normalized-artifact cache carries `_nx_normalizer_version`
   and the read rejects stale versions; the cache is keyed by the INPUT-based
   execution key on both read and write (previously write-only → dead cache).
3. **Contract validation at registration**: declared flat-field paths must
   resolve (or be `x-artifact-optional`); violations abort registration
   (never silent None) and surface as explicit errors.
4. **Execution→artifact invariant**: executor SUCCESS outcomes must have a
   registered artifact (by execution id); violations append an explicit
   error event before response synthesis.
5. **Response data-incorporation guard**: a synthesized answer engaging NONE
   of the registered artifact values is replaced by the deterministic
   Artifact Renderer (artifacts are never discarded by synthesis).
6. **Memory reinforcement gate**: `persist_after_response` skips error /
   `_synthesis_failed` / degenerate responses — failed responses never pollute
   planning memory.
7. **missing_producer rule** (PlanValidator): a literal REQUIRED input that a
   registered, chain-constructible capability produces → REFINE (bounded
   replan); the abort path routes to ResponseNode (honest failure, never a
   silent dead end).
8. **Compiler-failure recovery**: `CompilerError` (implicit placeholder-edge
   cycles) routes to a bounded replan (`_compile_retry_count`) then to
   ResponseNode; `_find_cycle` now mirrors the compiler's static dataflow
   (ref-keyed index + placeholder edges + legacy op-named deps).
9. **Graph edges added**: CompilerNode → {SemanticPlannerNode, ResponseNode};
   PlanValidatorNode → ResponseNode (abort). New state fields:
   `_compile_errors`, `_compile_retry_count` (declared in contracts +
   `_EPHEMERAL_FIELDS`).

## 10. Follow-up Amendments (P0–P2, 2026-08-07)

1. **P0 — honest failure propagation**: the route-side rounds cap intercepted
   one validator visit early, so the state still carried the last REFINE
   patch (`errors=[]`) when the response ran. The route no longer caps
   (the node's abort branch handles the bound) and the response's error
   branch surfaces the actual validator/compiler reason — the generic
   "I processed your request." can never mask an abort.
2. **P0 — precise data-incorporation guard**: `_synthesis_incorporates_data`
   now descends through the deep-frozen payloads (MappingProxyType) — the
   guard previously never matched real answers and forced the deterministic
   renderer on every tool turn. LLM narratives that cite artifact values
   now pass (verified live: natural weather prose returned).
3. **Permanent handoff gate**: `tests/test_handoff_invariant.py` (deterministic,
   runs in the non-live CI gate) — executor success ⇒ artifact registered ⇒
   contract valid ⇒ response references artifact ⇒ PASS; plus the abort-reason
   propagation test.
4. **P1 — typed renderers**: Weather/Country/Books/Exchange/Media renderers
   (presentation plugins; exchange reads any `*_rate` field). Fixed the
   missing `RendererRegistry.get` — the renderer path was silently broken
   and every artifact degraded to the raw-JSON preview.
5. **P2 — path-segment integrity**: a null-sentinel string (`"None"`) or a
   literal unresolved `${...}` can never fill a URL path segment or leak
   into the query string — absent values are stripped (optional) or raise
   (required), never `HTTP /posts/None`. Matrix gained the
   `parameter_resolution` scenario.

## 11. All-Phases Closure Amendments (2026-08-08)

1. **Intent-first validation (P4)**: the PlanValidator enforces intent
   coverage (units served by planned capabilities via the registry bridge),
   capability alignment (rank-based), parameter provenance (values must
   trace to the user request or a chain expression — guessed literals
   REFINE), and traceability (ops must trace to an intent unit or the
   producer chain; the non-forbidden class is a WARNING — precision bounded
   by the keyword map; negation-forbidden ops are hard errors). Empty plans
   for executable queries repair then clarify — never the training-knowledge
   answer.
2. **ReasoningBudget (P0)**: the per-invocation contract
   (`_invocation_budget`) — wall-time + graph steps (runner), replans
   (validator + compiler + recovery — ONE shared counter), tool calls
   (executor reserves), LLM calls (planner + response). Reserve-before-
   execute; `_invocation_status` terminal states; the `uncertain` outcome
   on mid-call cancellation is never retried.
3. **Execution gates (P0)**: authorization (`validation_rules.allowed_roles`
   vs the caller's roles), SSRF hardening for the dynamic-endpoint class,
   idempotency keys stable across retries (stamped via
   `validation_rules.idempotency_header`).
4. **Approval semantic binding (P1)**: decisions bind to the operation hash
   (policy + step + tools + inputs) — a modified/replanned step re-approves.
5. **Injection + memory (P1)**: finalize v4.1's untrusted-data boundary;
   the memory store attaches provenance (`observed_at`/`source`/`scope`/
   `confidence`) and optional `expires_at` (ttl_s) enforced by the scout.
6. **Compiler chain synthesis**: `RESOLVE("capability","key","value")` input
   expressions synthesize the producer node (metadata-driven; frozen IR
   rebuilt) — the planner's declarative chain intent is honored
   deterministically.
