# `src/nexus/api/` — FastAPI Application & Public API Layer

## Key Responsibilities

- `create_app()` — application factory with middleware stack (CORS, TrustedHost, RequestID, logging, tenant, rate limit, auth passthrough, error handling, drain, security headers).
- Route definitions: `/tools`, `/sessions`, `/chat`, `/approvals`, `/memory`, `/ws`.
- SSE and WebSocket endpoints for streaming agent responses.
- Graceful shutdown — drain middleware rejects new requests during shutdown.

## Key Files

| File | Responsibility |
|------|---------------|
| `main.py` | Application factory, middleware ordering, health checks |
| `routes.py` | Router aggregation under `/api/v1` |
| `chat.py` | Chat SSE streaming with heartbeat |
| `websocket.py` | Bidirectional WebSocket agent communication |
| `approvals.py` | HITL approval management |
| `memory.py` | Long-term memory CRUD |
| `depends.py` | Tenant/User dependency injection |

## Middleware Stack

1. CORSMiddleware
2. TrustedHostMiddleware
3. RequestIDMiddleware
4. LoggingMiddleware
5. TenantMiddleware
6. TieredRateLimitMiddleware
7. AuthMiddleware (passthrough — injects default identity)
8. ErrorHandlerMiddleware
9. DrainMiddleware
10. Security headers

## Dependencies

- `nexus/agent/` — AgentRunner for graph orchestration
- `nexus/sessions/` — SessionService
- `nexus/tools/` — ToolRegistry
- `nexus/memory/` — MemoryManager
