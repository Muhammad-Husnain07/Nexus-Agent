# Nexus Agent Platform

Monorepo containing:
- **`nexus-agent/`** — Python backend (FastAPI + LangGraph + PostgreSQL)
- **`frontend/`** — React management console (TypeScript + Tailwind CSS v4 + shadcn/ui + Vite)

## BINDING ENGINEERING PRINCIPLES

> **Read [`nexus-agent/docs/engineering-principles.md`](nexus-agent/docs/engineering-principles.md)
> before ANY code.** It is the binding rulebook: treat the agent as a
> distributed workflow engine with LLM-assisted decision-making (LLM
> proposes plans, deterministic layers enforce). Key rules: no hardcoded
> capability/domain logic; validate every plan before execution (coverage +
> traceability); never execute an invalid plan; typed errors; versioned
> cache keys via the architecture manifest (ADR 0008); never store failed
> responses; deterministic fallbacks; metrics before optimization.

## Architecture

The agent uses a **19-node deterministic workflow compiler** (intent-first):

```
RouterNode
  → ResponseNode (conversational) | InteractiveWorkflowNode (workflow)
  → RequirementCollectorNode (needs requirements) | SemanticPlannerNode (action)
SemanticPlannerNode (intent-unit planning) → PlanValidatorNode
PlanValidatorNode (coverage + alignment + provenance + traceability + budget)
  → CompilerNode (RESOLVE(...) producer-chain synthesis) → OptimizerNode → EstimatorNode
  → ValidationNode → ApprovalGateNode (semantic-bound approvals) → ExecutorNode
  → AggregatorNode (reduce on SUCCESS too) → ValidatorNode → RecoveryManagerNode
  → ReflectionNode (retry) | ReplanNode (shared-budget replan) | ResponseNode
  → MemoryHelperNode (provenance-stamped, gated) → END
```

The pipeline: Router classifies → SemanticPlanner emits `LogicalWorkflow` (one node per
detected intent unit) → **PlanValidator** verifies semantic completeness (intent coverage,
capability alignment, parameter provenance, traceability) and the invocation
**ReasoningBudget** → Compiler resolves tools (deterministic `RESOLVE(...)` chain
synthesis) → Optimizer/Estimator → Validation → Approval (bound to the exact
operation hash) → Executor (authorized, idempotent-keyed, cancellable, sandboxed with
SSRF hardening) → Recovery (every failure enters the typed recovery state machine) →
Response (data-incorporation + per-artifact coverage guards; deterministic renderer
fallback) → Memory (never stores failed responses; provenance + freshness).

Every capability, alias, keyword, and policy comes from the registry metadata — no
hardcoded domain logic anywhere. The architecture is versioned (ADR 0008:
`src/nexus/agent/architecture.py` — the single cache-key fingerprint).

## Phase status (architecture FROZEN)

| Phase | What | Status |
|---|---|---|
| P0-A | Deterministic resolver (CapabilitySemantics, generic suppression, branch-safe) | ✅ frozen |
| P0-B | Parameter/provenance binder (L1–L5, BOUND/MISSING/AMBIGUOUS/INVALID) | ✅ frozen |
| P0-C | Structured intent decomposition (IntentGraph, K83) + coverage | ✅ frozen |
| P0-D | Evidence compiler, grounding gate, synthesis repair, deterministic renderer | ✅ frozen |
| P1-A | Large-DAG efficiency (DROP_AND_PROCEED, alignment floor, wave timing) | ✅ frozen |
| P1-B | `_response_status` machine (SUCCESS/PARTIAL/EXECUTION_FAILED/PLANNING_FAILED) | ✅ frozen |
| P1-C | Bounded extraction recovery (diagnosed EMPTY_PLAN classes, one repair) | ✅ frozen |
| P1-D | Map/fan-out collapse (D48: 1 MAP node, cardinality 3) | ✅ frozen |
| P2-A | Hierarchical mega-DAG planning (chunked, coverage-invariant merge, collections guard) | ✅ frozen |

**Production model config** (`.env`): planner + synthesis =
`nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b` (`NEXUS_LLM__SYNTHESIS_MODEL`
override for hybrid configs); embeddings OFF
(`NEXUS_RESOLVER__ENABLE_EMBEDDING_RETRIEVAL=false` — no measured benefit at
22 tools).

**Benchmark baseline**: 98/135 × 3 reproducible (mean 91.1), binding 1.0,
artifacts 0.788, grounding 0.763. Full phase history + mega-DAG validation in
[`nexus-agent/docs/roadmap.md`](nexus-agent/docs/roadmap.md); the invariant
ledger (I1–I19) in [`nexus-agent/docs/invariants.md`](nexus-agent/docs/invariants.md).

**Post-freeze rule**: do not reopen the frozen orchestration architecture.
Model configuration and benchmark instrumentation are the only permitted
changes; further performance work is a separate P3 experiment with its own
A/B measurement (see the P2-A.5 chunk-timing baseline).

## Backend Rules

See [`nexus-agent/AGENTS.md`](nexus-agent/AGENTS.md) and [`nexus-agent/src/nexus/agent/AGENTS.md`](nexus-agent/src/nexus/agent/AGENTS.md).

## Frontend Rules

1. Frontend code lives in `frontend/`.
2. Always use TanStack Query for data fetching.
3. Use Tailwind CSS v4 for all styling; no custom CSS files.
4. All API responses must be typed with TypeScript interfaces in `src/types/`.
5. State management: TanStack Query (server state) + Zustand (client state).
6. Forms: React Hook Form + Zod validation.
7. Routing: React Router v6 with lazy-loaded routes in `src/routes/`.
8. Toast notifications: use `sonner` `toast()`.
9. Icons: use `lucide-react` (not `@mui/icons-material`).
10. Charts: use `recharts` components wrapped in shadcn `Card`.
11. Tables: use semantic HTML `<table>` with shadcn styling.
12. UI components from `src/components/ui/` (shadcn primitives).
13. Page components in `src/routes/` organized by feature.
14. Feature-specific components in `src/components/<feature>/`.
15. API proxy in `vite.config.ts` targets WSL2 backend at `172.27.173.1:8000`.
