# API Reference

The fastest way to explore the API is the auto-generated OpenAPI documentation:

| Tool | URL |
|------|-----|
| **Swagger UI** | [http://localhost:8000/docs](http://localhost:8000/docs) |
| **ReDoc** | [http://localhost:8000/redoc](http://localhost:8000/redoc) |
| **OpenAPI JSON** | [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json) |

---

## Endpoint Groups

### Tools API — `/api/v1/tools`

Register, discover, and manage tools that the agent can invoke.

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| `POST` | `/api/v1/tools` | Register a new tool | `tools:register` |
| `GET` | `/api/v1/tools` | List tools (paginated, filterable) | `tools:read` |
| `GET` | `/api/v1/tools/search?q=...` | Semantic search | `tools:read` |
| `GET` | `/api/v1/tools/{id}` | Get tool by ID | `tools:read` |
| `PUT` | `/api/v1/tools/{id}` | Update tool definition | `tools:register` |
| `DELETE` | `/api/v1/tools/{id}` | Soft-delete tool | `tools:delete` |
| `POST` | `/api/v1/tools/{id}/test` | Dry-run with sample input | `tools:read` |
| `GET` | `/api/v1/tools/{id}/versions/diff` | Compare tool versions | `tools:read` |

**See [Tool Registration Guide](tool-registration.md) for the full request/response schemas.**

---

### Sessions API — `/api/v1/sessions`

Conversation sessions group messages and provide context for the agent.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/sessions` | Create session |
| `GET` | `/api/v1/sessions` | List sessions (filter by user, status) |
| `GET` | `/api/v1/sessions/{id}` | Get session details |
| `PATCH` | `/api/v1/sessions/{id}` | Update session (rename, change status) |
| `DELETE` | `/api/v1/sessions/{id}` | Archive session |
| `POST` | `/api/v1/sessions/{id}/fork` | Fork conversation at a message |
| `POST` | `/api/v1/sessions/{id}/rename` | Auto-rename by LLM |
| `GET` | `/api/v1/sessions/{id}/messages` | Get message history |
| `POST` | `/api/v1/sessions/{id}/messages` | Add message |

---

### Chat API — `/api/v1/sessions/{session_id}/chat`

The main interaction endpoint. Streams agent events via SSE.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/sessions/{session_id}/chat` | Send message, receive SSE events |

**Request body:**
```json
{
  "message": "Send an email to john@example.com",
  "stream": true
}
```

- `stream: true` (default) — returns SSE event stream
- `stream: false` — returns JSON with all accumulated events

See [Integration Guide](integration-guide.md) for SSE client code and event reference.

---

### Approvals API — `/api/v1/approvals`

Human-in-the-loop decision management.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/approvals/pending/{session_id}` | List pending approvals for a session |
| `GET` | `/api/v1/approvals/pending` | List all pending approvals (current tenant) |
| `GET` | `/api/v1/approvals/{id}` | Get approval status |
| `POST` | `/api/v1/approvals/{id}/decide` | Approve/reject/edit |

See [HITL Guide](hitl.md) for the complete approval flow documentation.

---

### Agent API — `/api/v1/agent`

Direct agent graph access (advanced use cases).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/sessions/{session_id}/state` | Get current run state from checkpointer |

---

### Auth API — `/api/v1/auth`

Authentication and token management.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/auth/login` | Get access + refresh tokens |
| `POST` | `/api/v1/auth/refresh` | Refresh access token |
| `POST` | `/api/v1/auth/revoke` | Revoke refresh token |

---

### Memory API — `/api/v1/memory`

Long-term memory storage and semantic search.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/memory` | List/search memories (`?q=` for semantic, `?kind=` filter) |
| `GET` | `/api/v1/memory/{id}` | Get memory by ID |
| `DELETE` | `/api/v1/memory/{id}` | Delete a memory |

---

### WebSocket API — `/api/v1/sessions/{session_id}/ws`

Bidirectional real-time chat over WebSocket.

| Method | Path | Description |
|--------|------|-------------|
| `WS` | `/api/v1/sessions/{session_id}/ws` | Bidirectional real-time chat with pub/sub fan-out |

---

### Admin API — `/api/v1/admin`

Tenant and user management. Requires `tenant_admin` or `platform_admin` role.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/admin/tenants` | List all tenants (platform admin only) |
| `POST` | `/api/v1/admin/tenants` | Create tenant (platform admin only) |
| `GET` | `/api/v1/admin/tenants/{id}` | Get tenant details |
| `PATCH` | `/api/v1/admin/tenants/{id}` | Update tenant settings |
| `GET` | `/api/v1/admin/tenants/{id}/users` | List users in tenant |
| `POST` | `/api/v1/admin/tenants/{id}/users` | Create user |
| `GET` | `/api/v1/admin/tenants/{id}/api-keys` | List API keys |
| `POST` | `/api/v1/admin/tenants/{id}/api-keys` | Generate API key (plaintext returned once) |
| `DELETE` | `/api/v1/admin/tenants/{id}/api-keys/{key_id}` | Revoke API key |
| `PATCH` | `/api/v1/admin/users/{id}` | Update user |
| `GET` | `/api/v1/admin/audit-log` | Audit log access (platform admin only) |

---

### Cost API — `/api/v1/cost`

Usage and cost tracking.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/cost/summary` | Cost summary for period |
| `GET` | `/api/v1/cost/daily` | Per-day breakdown |
| `GET` | `/api/v1/cost/by-tenant` | Per-tenant breakdown (admin) |

---

### System Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/healthz` | Liveness check |
| `GET` | `/readyz` | Readiness check (DB + Redis) |
| `GET` | `/metrics` | Prometheus metrics |
| `GET` | `/docs` | Swagger UI |
| `GET` | `/redoc` | ReDoc |

### MCP Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/_mcp/tools/list` | List tools for MCP |
| `POST` | `/_mcp/tools/call` | Invoke tool via MCP |

See [MCP Guide](mcp.md) for details.
