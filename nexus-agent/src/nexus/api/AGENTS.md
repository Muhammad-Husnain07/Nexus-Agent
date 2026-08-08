# `src/nexus/api/` — FastAPI Application & Public API Layer

> **Runtime Contract** (binding): see [`docs/runtime-contract.md`](../../../docs/runtime-contract.md).
> The API is the runtime's public boundary — request/response bodies are typed
> Pydantic models; debug endpoints (`/tools/retrieve`, `/tools/resolution-index`)
> are read-only probes into resolution/retrieval state.

## Key Responsibilities

- `create_app()` — application factory with middleware stack (CORS, TrustedHost, RequestID, logging, rate limit, auth passthrough, error handling, drain, security headers).
- Route definitions: `/tools`, `/sessions`, `/chat`, `/memory`, `/ws`.
- SSE and WebSocket endpoints for streaming agent responses with heartbeat keep-alive.
- Graceful shutdown — drain middleware rejects new requests during shutdown, drains background tasks.
- Conversational approval checkpoints — no external approval screens; the gate pauses in-chat and the next message routes to ApprovalCheckpointResumeNode.
- Checkpoint recovery — restore graph to state before any named node.
- **GlobalContext initialization** — loads the `CompiledCapabilityGraph` at startup and initializes the O(1) capability→providers hash map via `GlobalContext.from_compiled_graph()`.

## Key Files

| File | Responsibility |
|------|---------------|
| `main.py` | Application factory, middleware ordering, health checks, graceful shutdown with background task drain |
| `routes.py` | Router aggregation under `/api/v1` — includes tools, sessions, chat, websocket, memory |
| `chat.py` | Chat SSE streaming with heartbeat keep-alive, `_stream_response` and `_json_response` modes |
| ~~`approvals.py`~~ | **Removed** — external HITL approvals router deleted; approval is conversational via ApprovalCheckpointResumeNode |
| `websocket.py` | Bidirectional WebSocket agent communication |
| `memory.py` | Long-term memory CRUD |
| `depends.py` | Dependency injection — `get_agent_runner()` creates wired AgentRunner per request |
| `schemas.py` | Request/response models: `ChatRequest`, `ChatResponse` |

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/sessions/{id}/chat` | Send a message, stream SSE events (tool_selected, plan_created, approval_checkpoint, final_response, node_completed) |
| GET | `/sessions/{id}/state` | Get current graph state (completed/running, current_node, final_response) |
| ALL | `/tools/*` | Tool CRUD — register, list, search, get, update, delete, test |

## SSE Events

| Event | Emitted When |
|-------|-------------|
| `node_completed` | Every node finishes — includes `duration_ms` and `has_output` |
| `tool_selected` | RouterNode classifies the query |
| `plan_created` | PlannerNode/TaskGraphBuilderNode produces execution plan |
| `tool_call_completed` | Each tool finishes execution |
| `approval_checkpoint` | ApprovalGateNode pauses — user decides in-chat (approve/reject/cancel/modify/clarify) |
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

- `nexus/agent/` — AgentRunner for the 19-node graph orchestration
- `nexus/sessions/` — SessionService
- `nexus/tools/` — ToolRegistry
- `nexus/memory/` — MemoryManager, checkpointer
- `nexus/compiler/` — CompiledCapabilityGraph for offline-compiled capability data
- `nexus/context/` — GlobalContext for O(1) capability→providers lookup at startup
