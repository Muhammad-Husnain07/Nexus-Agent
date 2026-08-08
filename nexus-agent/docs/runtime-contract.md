# Nexus Runtime Contract

> **Phase 0 deliverable.** This document is the architectural guardrail for every
> contributor and every future change. It defines the invariants, the typed
> contracts between subsystems, and the side-effect rules. Code that violates
> these invariants is a defect — not a style choice.
>
> Scope: the **Nexus Agent Orchestration Runtime** (backend `nexus-agent/`).
> Frontend (management console + embed widget) is a client of the runtime's
> public API and must never reach into runtime internals.

---

## 1. Core Invariants

The runtime is deterministic orchestration around probabilistic planning. The
following invariants hold **always**:

1. **The Resolution Engine is pure and side-effect free.** It answers "what is
   relevant?" — it performs no DB writes, no Redis mutations, no embedding
   generation, no HTTP calls. All inputs (catalog, indexes, availability
   facts) are injected as readers; the engine returns a `ResolutionResult`.
2. **The Planner defines *what*, never *how*.** It emits an intent/goal and a
   logical workflow (nodes + dependencies). Execution concerns (strategies,
   policies, waves, retries) are decided by deterministic layers — never by
   the planner, never in the planner prompt.
3. **The Compiler produces executable graphs only.** Input is a validated
   logical workflow; output is a physical `ExecutionGraph` with typed nodes
   and topologically ordered waves. No planning, no LLM, no side effects.
4. **The Executor never replans.** It executes the compiled graph, resolves
   placeholders, honors policies, and reports results. If a step fails, the
   recovery path (reflection/self-healing) is graph-level, not plan-level.
5. **Policies are metadata, not logic.** Approval, retry, timeout, cache,
   parallel, budget, risk, rollback, and availability live in capability
   metadata (`contract`/`execution_policy`) — not in `if` statements over
   tool names, and not hardcoded anywhere.
6. **Validation precedes compilation.** The `PlanValidatorNode` rejects
   undefined ops, cycles, missing inputs, schema mismatches, budget
   violations, and policy violations *before* the compiler runs.
7. **Plans never include unavailable capabilities.** Availability is a fact
   (`enabled`, circuit state, rate-limit headroom, maintenance) resolved
   before planning; the planner never sees disabled/unavailable candidates.
8. **Artifacts are immutable after publication.** Published artifact data is
   frozen; revisions are new versions, never in-place edits.
9. **ExecutionContext is immutable.** Nodes receive `Context(v)` and return
   `Context(v+1)` via `StatePatch`. Shared singletons are replaced by atomic
   whole-object swap (`set_global_context`), never mutated in place.
10. **Every executable implements an Execution Contract.** Capabilities,
    workflows, macros, composites, and background jobs normalize to the same
    `{inputs, outputs, permissions, policies, guarantees, rollback, timeout,
    checkpoint, expected_artifacts}` shape. No special cases.
11. **Every phase/subsystem is independently testable.** Purity makes this
    possible: deterministic layers test with fakes; the LLM is never required
    by a unit test.
12. **User denial terminates the requested action** unless the denied step is a
    required dependency whose removal still permits the planner to satisfy the
    user's broader goal — only then does the runtime replan (a denial is a
    user decision, not a signal to find another way).
13. **Recovery is one decision point.** The `RecoveryManager` classifies every
    failure into exactly one strategy — `RETRY` (transient → Reflection),
    `SELF_HEAL` (contract + fallback), `REPLAN` (structural invalidity:
    unavailable capability, schema change, policy violation — bounded rounds),
    or `FAIL` (explicit). Reflection is a strategy, not the recovery layer.
14. **Executions are replayable.** Every background execution carries an
    immutable `ExecutionRequest` (execution_id + implementation versions) and
    produces a typed `ExecutionResult`; version fields are module constants,
    never settings.

---

## 2. Typed Contracts — No Implicit Conventions

Communication between subsystems occurs **only** through explicit, immutable
Pydantic models. No `dict` payloads, no shared mutable state, no implicit
field-name conventions across boundaries.

### 2.1 Boundary Map

| Boundary | Contract model | Status |
|---|---|---|
| Resolver → Router / Planner | `ResolutionResult` (+ `CapabilityCandidate`, `WorkflowCandidate`, `ResolutionMetadata`) | Phase 1 |
| Router → Graph | `ExecutionGoal` flag set + `primary_goal` + `needs_requirements` modifier | Phase 2 |
| Planner → Validator | `LogicalWorkflow` (nodes, `depends_on`, `iterate_over`) | now |
| Validator → Compiler | `PlanValidatorReport` (violations, severity, action) | Phase 3 |
| Strategy → Compiler | `ExecutionStrategy` (sequential/parallel/map/reduce/retry/background/streaming) | Phase 4 |
| Compiler → Executor | `ExecutionGraph` (typed physical nodes, waves) | now |
| Executor → Runtime | `ToolResult` / `ToolExecutionResult` | now |
| Memory → Planner | `MemoryRetrievalResult` (bounded snippets) | Phase 5 |
| Node → UI/SSE | typed event models (one per event type) | Phase 7 |
| Registry stores | typed store classes behind interfaces; atomic swap | Phase 1+ |
| Artifacts | `ArtifactRecord` (schema, version, relationship, ownership, lifecycle) | Phase 8 |
| Everything executable | `ExecutionContract` | Phase 9 |

### 2.2 Rules

1. **No `dict[str, Any]` crosses a subsystem boundary.** Where a model is not
   yet defined (see roadmap), the boundary is marked "in progress" — do not
   fossilize the dict, migrate it.
2. **Frozen models.** `ResolutionResult`, candidates, metadata, policies, and
   contracts are `frozen=True`. Consumers copy when they need to derive.
3. **Stable IDs, not names.** Cross-subsystem references use IDs
   (`tool.id`, workflow row id). Names are display-only and change.
4. **Machine-readable + human-readable.** Structured fields (`match_sources`,
   `availability`) for logic; `reasons`/`explanation` for debugging and
   telemetry — never parsed by logic.

---

## 3. Side-Effect Rules

1. **No writes to shared singletons.** The only allowed mutation pattern is
   atomic replacement (`set_global_context(ctx)`). In-place mutation of
   `GlobalContext`, the retriever singleton, breaker stores, or performance
   trackers is forbidden.
2. **No hidden I/O in pure layers.** `capabilities/` resolution code performs
   no DB/Redis/LLM/HTTP side effects. Readers are injected (`gc`, sessions,
   registry clients).
3. **Side effects live in adapters.** Registry sync, persistence, embedding
   generation, event publishing — adapter layers only, never inside IR/plan/
   contract logic.
4. **No hidden retries or fallbacks.** Retry budgets are explicit metadata
   (`idempotent` → retries allowed; non-idempotent → single attempt).
5. **Failure is explicit, never silent.** Unresolved ops, dropped plans, and
   validation failures surface as `errors[]`/`PlanValidatorReport` entries —
   no guessing, no silent fallthrough.

---

## 4. Enforcement

Per-phase gate (checked by tests and review before a phase is "done"):

1. New subsystem exposes its typed contract (models in `src/nexus/…` next to
   the code, `frozen=True` where specified).
2. Pure-layer purity test: no DB/Redis/HTTP touched with fake readers.
3. Boundary grep gate: no `dict[str, Any]` payloads added across new
   boundaries; no new module-global mutable stores.
4. Immutability tests: frozen models reject mutation; `ExecutionContext`
   transitions verified.
5. Full suite green (baseline 102 backend / 20 frontend) + E2E with the
   registered demo tools.

## 5. Related Documents

- [`README.md`](README.md) — docs index
- [`roadmap.md`](roadmap.md) — the phased implementation plan (0–9)
- [`architecture.md`](architecture.md) — current runtime architecture
- [`AGENTS.md`](../../AGENTS.md) — root working rules (includes these invariants)
