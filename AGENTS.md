# Nexus Agent Platform

Monorepo containing:
- **`nexus-agent/`** — Python backend (FastAPI + LangGraph + PostgreSQL)
- **`frontend/`** — React frontend (Vite + TypeScript + shadcn/ui)

## Backend Rules

See [`nexus-agent/AGENTS.md`](nexus-agent/AGENTS.md).

## Frontend Rules

1. Frontend code lives in `frontend/`.
2. Always use TanStack Query for data fetching.
3. Use shadcn/ui components; do not write custom CSS unless absolutely necessary.
4. All API responses must be typed with TypeScript interfaces in `lib/types.ts`.
5. State management: TanStack Query (server state) + Zustand (client state).
6. Forms: React Hook Form + Zod validation.
7. Routing: React Router v6 with lazy-loaded routes.
