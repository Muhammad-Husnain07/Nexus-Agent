# Quickstart — First Chat in 15 Minutes

This guide walks you through starting the platform, registering a tool, and chatting with the agent — all in under 15 minutes.

---

## Prerequisites

- **Docker** & **docker compose** (v2.24+)
- **curl** or **httpie**
- **Python 3.12+** (for optional SDK usage)
- An **LLM provider API key** (OpenAI, Anthropic, DeepSeek, Google Gemini, etc.)

> **Provider setup:** Export your API key as an environment variable before starting:
> ```bash
> # OpenAI
> export OPENAI_API_KEY=sk-...
> # OR DeepSeek
> export DEEPSEEK_API_KEY=sk-...
> # OR Anthropic
> export ANTHROPIC_API_KEY=sk-ant-...
> ```
> Then set the model in `.env`:
> ```bash
> echo "NEXUS_LLM__DEFAULT_MODEL=deepseek/deepseek-chat" >> .env
> ```
> LiteLLM handles routing to the correct provider based on the model prefix.
> See [LiteLLM providers](https://docs.litellm.ai/docs/providers) for all supported providers.

---

## Step 1: Start the Stack

```bash
# Clone and enter the repo
git clone https://github.com/your-org/nexus-agent
cd nexus-agent

# Start PostgreSQL, Redis, and the app
docker compose -f docker/docker-compose.yml up -d
```

This starts three services:
- `nexus-agent` — the FastAPI application (port 8000)
- `postgres` — PostgreSQL 16 + pgvector (port 5433)
- `redis` — Redis 7 (port 6379)

**Verify:**
```bash
# Liveness check
curl http://localhost:8000/healthz
# → {"status":"ok","version":"0.1.0"}

# Readiness check
curl http://localhost:8000/readyz
# → {"status":"ok","database":"ok","redis":"ok"}
```

---

## Step 2: Create a Tenant & API Key

```bash
# Create a session and get a JWT (stub — no password required for dev)
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com"}'
# → {"access_token":"eyJ...","refresh_token":"eyJ...","token_type":"bearer"}
```

Save the `access_token` — you'll use it as `Authorization: Bearer <token>`.

*(In production, configure proper auth: set `NEXUS_AUTH__JWT_SECRET` and use real credentials.)*

---

## Step 3: Register a Tool

Register a simple "echo" tool that mirrors back input:

```bash
curl -X POST http://localhost:8000/api/v1/tools \
  -H "Authorization: Bearer <your-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "echo",
    "description": "Echoes back the user input. Useful for testing.",
    "purpose": "Test the tool execution pipeline.",
    "endpoint_url": "https://httpbin.org/post",
    "http_method": "POST",
    "input_schema": {
      "type": "object",
      "properties": {
        "msg": {"type": "string", "description": "Message to echo"}
      },
      "required": ["msg"]
    },
    "output_schema": {
      "type": "object",
      "properties": {
        "echo": {"type": "string"}
      }
    },
    "tags": ["test", "demo"],
    "category": "utilities",
    "risk_level": "low"
  }'
# → 201 Created with the full tool definition
```

---

## Step 4: Create a Session

```bash
curl -X POST http://localhost:8000/api/v1/sessions \
  -H "Authorization: Bearer <your-token>" \
  -H "Content-Type: application/json" \
  -d '{"title": "My first session"}'
# → {"id":"uuid","title":"My first session","status":"active",...}
```

Save the `id` — you'll use it as the `session_id`.

---

## Step 5: Chat (SSE Streaming)

```bash
curl -X POST http://localhost:8000/api/v1/sessions/{session_id}/chat \
  -H "Authorization: Bearer <your-token>" \
  -H "Content-Type: application/json" \
  -d '{"message": "Say hello back to me", "stream": true}'
```

You'll see SSE events streaming back:
```
event: plan_created
data: {"type":"plan_created","ts":"...","payload":{"steps":[...]}}

event: tool_call_completed
data: {"type":"tool_call_completed","ts":"...","payload":{"tool_name":"echo","status":"success",...}}

event: final_response
data: {"type":"final_response","ts":"...","payload":{"text":"Hello! I echoed your message."}}

event: done
data: {}
```

**For a non-streaming response:**
```bash
curl -X POST http://localhost:8000/api/v1/sessions/{session_id}/chat \
  -H "Authorization: Bearer <your-token>" \
  -H "Content-Type: application/json" \
  -d '{"message": "Say hello back to me", "stream": false}'
# → {"final_response":"Hello!","events":[...]}
```

---

## Step 6: View the API Docs

Open [http://localhost:8000/docs](http://localhost:8000/docs) in your browser for the full OpenAPI Swagger UI.

---

## What's Next

| Guide | Description |
|-------|-------------|
| [Tool Registration](tool-registration.md) | Full schema reference, auth types, best practices |
| [Integration Guide](integration-guide.md) | Embed the chatbot, SSE/WS client code, HITL UX |
| [MCP Integration](mcp.md) | Consume tools via Model Context Protocol |
| [API Reference](api-reference.md) | All endpoints with examples |
| [Operations Guide](operations.md) | Deployment, scaling, monitoring, runbook |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `docker compose up` fails | Check Docker is running: `docker ps` |
| `/readyz` shows degraded | Wait for Postgres/Redis health checks (10-15s) |
| `401 Unauthorized` | Login again or check your token hasn't expired (default 30 min) |
| No SSE events received | Ensure `stream: true` in the request body |
| Tool returns 404 | The tool's `endpoint_url` must be accessible from the container |
