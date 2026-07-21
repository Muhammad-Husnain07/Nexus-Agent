# API Reference

All endpoints are prefixed with `/api/v1`.

## Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/healthz` | Health check |
| GET | `/readyz` | Readiness check |

## Tools

| Method | Path | Description |
|--------|------|-------------|
| POST | `/tools` | Register a new tool |
| GET | `/tools` | List tools (pagination, filters) |
| GET | `/tools/search` | Semantic search tools |
| GET | `/tools/{id}` | Get tool by ID |
| PUT | `/tools/{id}` | Update tool |
| DELETE | `/tools/{id}` | Delete tool |
| POST | `/tools/{id}/test` | Test tool execution |
| GET | `/tools/{id}/versions/diff` | Compare tool versions |

## Sessions

| Method | Path | Description |
|--------|------|-------------|
| POST | `/sessions` | Create session |
| GET | `/sessions` | List sessions |
| GET | `/sessions/{id}` | Get session details |
| PATCH | `/sessions/{id}` | Update session |
| DELETE | `/sessions/{id}` | Archive session |
| POST | `/sessions/{id}/fork` | Fork session |
| POST | `/sessions/{id}/rename` | Auto-rename session |
| GET | `/sessions/{id}/messages` | Get messages |
| POST | `/sessions/{id}/messages` | Add message |
| POST | `/sessions/{id}/chat` | Send chat message (stream/non-stream) |

## Approvals (Inline)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/approvals/pending` | List all pending approvals |
| GET | `/approvals/pending/{session_id}` | List pending for session |
| GET | `/approvals/{id}` | Get approval status |
| POST | `/approvals/{id}/decide` | Approve/reject/edit. Use `?stream=true` for SSE response |

Approvals appear inline in the chat SSE stream via `approval_required` events.
The decide endpoint resumes execution and streams results back via SSE when `?stream=true`.

## Memory

| Method | Path | Description |
|--------|------|-------------|
| GET | `/memory` | List/search memories |
| GET | `/memory/{id}` | Get memory by ID |
| DELETE | `/memory/{id}` | Delete memory |

## WebSocket

| Path | Description |
|------|-------------|
| `/api/v1/sessions/{id}/ws` | Real-time agent events |
