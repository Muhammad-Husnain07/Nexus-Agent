# Nexus Agent Platform

Monorepo containing:
- **`nexus-agent/`** — Python backend (FastAPI + LangGraph + PostgreSQL)
- **`frontend/`** — React management console (TypeScript + Tailwind CSS v4 + shadcn/ui + Vite)

## Architecture

The agent uses a **13-node deterministic workflow compiler**:
```
RouterNode → SemanticPlannerNode → CompilerNode → OptimizerNode → EstimatorNode → ValidationNode
    │                                                                                     │
    │                          ┌──────────────────────────────────────────────────────────┘
    │                          ▼
    │                   ClarificationNode (0 nodes → ResponseNode)
    │                          │
    │                   ApprovalGateNode → ExecutorNode → AggregatorNode → ReflectionNode → ResponseNode → MemoryHelperNode → END
```

The pipeline: Router classifies → SemanticPlanner emits `LogicalWorkflow` → Compiler resolves tools → Optimizer runs fixpoint passes → Estimator checks budget → Validation routes to approval/clarification. Tools execute in parallel waves with per-domain adaptive concurrency. Failed tasks are structurally graph-diffed and retried via `ReflectionNode`. High-risk tools require HITL approval via `ApprovalGateNode`.

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
