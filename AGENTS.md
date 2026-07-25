# Nexus Agent Platform

Monorepo containing:
- **`nexus-agent/`** — Python backend (FastAPI + LangGraph + PostgreSQL)
- **`frontend/`** — React management console (TypeScript + Tailwind CSS v4 + shadcn/ui + Vite)

## Architecture

The agent uses an **11-node production LangGraph**:
```
RouterNode → ExtractionNode → NormalizationNode → ContextMergeNode → ValidationNode
    │                                                                │
    │                          ┌─────────────────────────────────────┘
    │                          ▼
    │                   ClarificationNode (missing info → END)
    │                          │
    │                   PlannerNode → ApprovalGateNode → ExecutorNode → ReflectionNode → ResponseNode → END
```

Query routing: `NO_TOOL_NEEDED` goes directly to `ResponseNode`; all other types go through extraction → normalization → validation → clarification/planning → execution. Failed tasks auto-retry via `ReflectionNode` (configurable via settings, default 2x with backoff). High-risk tools require HITL approval via `ApprovalGateNode` before execution.

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
