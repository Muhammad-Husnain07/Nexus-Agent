# `src/nexus/api/` — FastAPI Application & Public API Layer

This module owns the FastAPI application factory, middleware stack, and all public API endpoints. It is the entry point for all external communication.

## Key Responsibilities

- `create_app()` — application factory with full middleware stack (CORS, TrustedHost, RequestID, structured logging, tenant resolution, rate limiting, auth, error handling, drain/graceful shutdown, security headers).
- Route definitions: `/chat`, `/sessions`, `/tools`, `/agent`, `/approvals`, `/admin`, `/auth`, `/health`, `/metrics`.
- SSE and WebSocket endpoints for streaming agent responses in real time.
- Middleware: tenant extraction (X-Tenant-ID / JWT / API key), authn/authz (Bearer JWT + API key fallback), rate limiting (tiered per tenant), request ID propagation.
- OpenAPI schema generation with Bearer JWT + API Key auth schemes documented.
- Graceful shutdown — drain middleware rejects new requests, waits for in-flight agent runs (up to 30s), closes SSE connections.

## Key Files

| File | Responsibility |
|------|---------------|
| `main.py` | `create_app()` — lifespan (init Redis, ProviderRegistry, ToolRegistry, MCP, scheduler), middleware ordering, health checks `/healthz` + `/readyz`, OpenAPI customization, router mounting |
| `routes.py` | Central router aggregating all sub-routers under `/api/v1` |
| `chat.py` | `POST /api/v1/sessions/{session_id}/chat` — SSE streaming (15s heartbeat) + JSON fallback; tracks active SSE connections |
| `websocket.py` | `WS /api/v1/sessions/{session_id}/ws` — bidirectional messaging with Redis pub/sub fan-out, ping/pong, cancel support |
| `approvals.py` | `GET/POST /api/v1/approvals/` — pending list, get by id, decide (approve/reject/edit) with auto-reject on timeout |
| `admin.py` | Admin endpoints — tenant CRUD, user CRUD, audit log access; requires `tenant_admin` role |
| `dependencies.py` | FastAPI `Depends` — `SessionServiceDep`, `AgentRunnerDep`, `ToolRegistryDep`, `SessionDep` |
| `depends.py` | Lightweight `TenantDep`, `UserDep` without circular imports |
| `schemas.py` | `ChatRequest`, `ChatResponse` Pydantic models |

## Middleware Stack (outermost first)

1. **CORSMiddleware** — configurable origins
2. **TrustedHostMiddleware** — host header validation (if origins != `["*"]`)
3. **RequestIDMiddleware** — propagate/generate `X-Request-ID`
4. **LoggingMiddleware** — structured request/response logging via structlog
5. **TenantMiddleware** — extract `X-Tenant-ID`, validate tenant exists and is active, set contextvar
6. **TieredRateLimitMiddleware** — per-tenant sliding-window rate limiting via Redis
7. **AuthMiddleware** — try Bearer JWT, fallback to `X-API-Key` with SHA-256 hash lookup
8. **ErrorHandlerMiddleware** — map domain exceptions to structured HTTP error JSON
9. **DrainMiddleware** — reject non-essential requests during graceful shutdown (503)
10. **Security headers** — HSTS, X-Content-Type-Options, X-Frame-Options, CSP for docs

## Event Types (SSE)

| Event | Source | Payload |
|-------|--------|---------|
| `plan_created` | plan node | `{steps: [...]}` |
| `tool_call_started` | execute_step | `{tool_name, inputs}` |
| `tool_call_completed` | execute_step | `{tool_name, status, data, error}` |
| `clarification_needed` | gather_requirements | `{question}` |
| `approval_required` | hitl_middleware | `{tool_name, inputs, approval_id}` |
| `intermediate_preview` | present_preview | `{text}` |
| `final_response` | finalize / any | `{text}` |
| `error` | any node | `{message, errors}` |
| `done` | stream end | `{}` |

## Dependencies

- `nexus/agent/` — AgentRunner, graph API for resume/approve/reject
- `nexus/sessions/` — SessionService for message + session management
- `nexus/tools/` — ToolRegistry for tool admin endpoints
- `nexus/security/` — AuthMiddleware, TenantMiddleware, RBAC dependencies
- `nexus/errors/` — ErrorHandlerMiddleware for structured error responses
- `nexus/observability/` — LoggingMiddleware, metrics endpoint
- `nexus/middleware/` — TenantMiddleware, AuthMiddleware
