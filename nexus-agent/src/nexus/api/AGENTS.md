# `src/nexus/api/` — FastAPI Application & Public API Layer

## Key Responsibilities

- `create_app()` — application factory with middleware stack (CORS, TrustedHost, RequestID, logging, rate limit, auth passthrough, error handling, drain, security headers).
- Route definitions: `/tools`, `/sessions`, `/chat`, `/approvals`, `/memory`, `/ws`.
- SSE and WebSocket endpoints for streaming agent responses with heartbeat keep-alive.
- Graceful shutdown — drain middleware rejects new requests during shutdown, drains background tasks.
- HITL approval management — approve/reject pending high-risk tool executions via checkpointer state injection.
- Checkpoint recovery — restore graph to state before any named node.

## Key Files

| File | Responsibility |
|------|---------------|
| `main.py` | Application factory, middleware ordering, health checks, graceful shutdown with background task drain |
| `routes.py` | Router aggregation under `/api/v1` — includes tools, sessions, chat, websocket, memory, approvals |
| `chat.py` | Chat SSE streaming with heartbeat keep-alive, `_stream_response` and `_json_response` modes |
| `approvals.py` | HITL approval management — `POST /approve`, `POST /reject`, `POST /recover`, `POST /recover/{node_name}` |
| `websocket.py` | Bidirectional WebSocket agent communication |
| `memory.py` | Long-term memory CRUD |
| `depends.py` | Dependency injection — `get_agent_runner()` creates wired AgentRunner per request |
| `schemas.py` | Request/response models: `ChatRequest`, `ChatResponse` |

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/sessions/{id}/chat` | Send a message, stream SSE events (tool_selected, plan_created, approval_required, final_response, node_completed) |
| GET | `/sessions/{id}/state` | Get current graph state (completed/running, current_node, final_response) |
| POST | `/sessions/{id}/approve` | Approve pending high-risk tool executions |
| POST | `/sessions/{id}/reject` | Reject pending high-risk tool executions |
| POST | `/sessions/{id}/recover` | Recover graph to penultimate checkpoint |
| POST | `/sessions/{id}/recover/{node}` | Recover graph to checkpoint before named node |
| ALL | `/tools/*` | Tool CRUD — register, list, search, get, update, delete, test |

## SSE Events

| Event | Emitted When |
|-------|-------------|
| `node_completed` | Every node finishes — includes `duration_ms` and `has_output` |
| `tool_selected` | RouterNode classifies the query |
| `plan_created` | PlannerNode/TaskGraphBuilderNode produces execution plan |
| `tool_call_completed` | Each tool finishes execution |
| `approval_required` | ApprovalGateNode detects high-risk tool |
| `final_response` | ResponseNode/ClarificationNode completes |
| `reflection_result` | ReflectionNode decides to retry |
| `error` | Any node produces errors |
| `done` | Stream ends — data is `{}` |

## SSE Event Format

```json
event: final_response
data: {"type": "final_response", "ts": "2026-07-26T00:00:00.000000+00:00", "payload": {"text": "Pikachu is an Electric-type Pokémon..."}}

event: done
data: {}
```

## Middleware Stack

1. CORSMiddleware
2. TrustedHostMiddleware
3. RequestIDMiddleware
4. LoggingMiddleware
5. TieredRateLimitMiddleware
6. AuthMiddleware (passthrough — injects default identity)
7. ErrorHandlerMiddleware
8. DrainMiddleware
9. Security headers

## Dependencies

- `nexus/agent/` — AgentRunner for 13-node graph orchestration
- `nexus/sessions/` — SessionService
- `nexus/tools/` — ToolRegistry
- `nexus/memory/` — MemoryManager, checkpointer
- `nexus/compiler/` — CompiledCapabilityGraph for offline-compiled capability data
