# Nexus Agent Platform

Monorepo containing:
- **`nexus-agent/`** — Python backend (FastAPI + LangGraph + PostgreSQL)
- **`frontend/`** — React management console (TypeScript + MUI v9 + Vite)

## Backend Rules

See [`nexus-agent/AGENTS.md`](nexus-agent/AGENTS.md).

## Frontend Rules

1. Frontend code lives in `frontend/`.
2. Always use TanStack Query for data fetching.
3. Use MUI `sx` prop for all styling; do not write custom CSS.
4. All API responses must be typed with TypeScript interfaces in `src/types/`.
5. State management: TanStack Query (server state) + Zustand (client state).
6. Forms: React Hook Form + Zod validation.
7. Routing: React Router v6 with lazy-loaded routes.
8. Toast notifications: use `notistack` `enqueueSnackbar()`.
9. Icons: use `@mui/icons-material` (not `lucide-react`).
10. Charts: use `recharts` components wrapped in MUI Card.
11. Data tables: use `@mui/x-data-grid` (community edition).
12. File structure by feature (not by type): `features/<name>/` for complex features.
