# Quickstart — 15 Minutes to Your First Chat

This guide walks you through starting the platform, configuring an LLM provider, and chatting with the agent.

---

## Prerequisites

- **Docker & docker compose** (v2.24+) — for PostgreSQL + Redis
- **Python 3.12+** and **[uv](https://docs.astral.sh/uv/)** package manager
- An **LLM provider** — Ollama (free, local) is recommended for development

---

## Choose Your Platform

### Linux / WSL2 (Recommended for Production)

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone repo
git clone https://github.com/Muhammad-Husnain07/Nexus-Agent.git
cd Nexus-Agent

# Set up environment
uv sync
cp .env.example .env
```

> **Linux advantage**: `AsyncPostgresSaver` works natively — agent state persists across restarts.

### Windows (Native)

```powershell
# Ensure Docker Desktop is running (with WSL2 backend)
# Install Python 3.12 from python.org, then install uv:
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Clone and set up
git clone https://github.com/Muhammad-Husnain07/Nexus-Agent.git
cd Nexus-Agent
uv sync
copy .env.example .env
```

> **Windows note**: `AsyncPostgresSaver` requires Linux — the app falls back to `MemorySaver`. State is kept in-process and lost on restart. For persistent state, use WSL2 or deploy to Linux.

---

## Choose Your LLM Provider

Pick one of the following configurations and set it in your `.env` file.

### Provider A: Ollama (Free, Local — Recommended for Dev)

```bash
# 1. Install Ollama (https://ollama.com)
# 2. Pull models:
ollama pull qwen2.5:7b
ollama pull nomic-embed-text

# 3. Set in .env:
cat >> .env << 'EOF'
NEXUS_LLM__DEFAULT_PROVIDER=ollama
NEXUS_LLM__DEFAULT_MODEL=ollama/qwen2.5:7b
NEXUS_LLM__EMBEDDING_MODEL=ollama/nomic-embed-text
NEXUS_LLM__TEMPERATURE=0.3
NEXUS_LLM__MAX_TOKENS=4096
NEXUS_LLM__TIMEOUT_S=300
NEXUS_LLM__MAX_RETRIES=3
NEXUS_LLM__PROVIDERS=[]
EOF
```

> **WSL2 users**: Ollama runs inside WSL2. The app can run on Windows (`localhost:11434` is forwarded automatically) or inside WSL2.

### Provider B: OpenAI

```bash
cat >> .env << 'EOF'
NEXUS_LLM__DEFAULT_PROVIDER=openai
NEXUS_LLM__DEFAULT_MODEL=gpt-4o
NEXUS_LLM__EMBEDDING_MODEL=text-embedding-3-small
NEXUS_LLM__TEMPERATURE=0.3
NEXUS_LLM__MAX_TOKENS=4096
NEXUS_LLM__PROVIDERS=[]
EOF
```

Then set your API key:
```bash
# Linux / macOS
export OPENAI_API_KEY=sk-...
# Windows PowerShell
$env:OPENAI_API_KEY="sk-..."
```

### Provider C: DeepSeek (OpenAI-Compatible)

```bash
cat >> .env << 'EOF'
NEXUS_LLM__DEFAULT_PROVIDER=deepseek
NEXUS_LLM__DEFAULT_MODEL=deepseek/deepseek-chat
NEXUS_LLM__EMBEDDING_MODEL=deepseek/deepseek-chat
NEXUS_LLM__TEMPERATURE=0.3
NEXUS_LLM__MAX_TOKENS=4096
NEXUS_LLM__PROVIDERS=[]
EOF
export DEEPSEEK_API_KEY=sk-...
```

### Provider D: Custom OpenAI-Compatible (LM Studio, vLLM, TGI, etc.)

For any server that exposes an OpenAI-compatible `/v1/chat/completions` endpoint:

```bash
cat >> .env << 'EOFMARKER'
NEXUS_LLM__DEFAULT_PROVIDER=openai
NEXUS_LLM__DEFAULT_MODEL=local-model
NEXUS_LLM__EMBEDDING_MODEL=local-model
NEXUS_LLM__TEMPERATURE=0.3
NEXUS_LLM__MAX_TOKENS=4096
NEXUS_LLM__PROVIDERS=[{"name":"openai","base_url":"http://localhost:1234/v1","api_key_ref":"CUSTOM_API_KEY","models":["local-model"],"cost_per_1k_input":0.000,"cost_per_1k_output":0.000,"max_tokens":8192,"supports_streaming":true,"supports_tools":true,"supports_structured_output":true}]
CUSTOM_API_KEY=sk-no-auth-required
EOFMARKER
```

Replace `http://localhost:1234/v1` with your server's URL.

### Other LiteLLM Providers

LiteLLM supports 100+ providers (Anthropic, Groq, OpenRouter, Google Gemini, AWS Bedrock, etc.).
For any provider, set the model with its prefix:

```
NEXUS_LLM__DEFAULT_MODEL=anthropic/claude-sonnet-4-20250514
NEXUS_LLM__DEFAULT_MODEL=groq/llama3-70b-8192
NEXUS_LLM__DEFAULT_MODEL=openrouter/anthropic/claude-3.5-sonnet
NEXUS_LLM__DEFAULT_MODEL=gemini/gemini-2.0-flash
```

See [LiteLLM Providers](https://docs.litellm.ai/docs/providers) for the full list.

---

## Step 1: Start PostgreSQL + Redis

```bash
docker compose -f docker/docker-compose.yml up -d
```

This starts:
- **postgres**: PostgreSQL 16 + pgvector (port 5433)
- **redis**: Redis 7 (port 6379)

**Verify:**

```bash
curl http://localhost:8000/healthz
# → {"status":"ok","version":"0.1.0"}
```

(Server not running yet — this is just a connectivity check.)

---

## Step 2: Configure Environment

```bash
# Edit .env with your LLM provider settings (see "Choose Your LLM Provider" above)
# For Ollama, the default .env.example works as-is:

# Generate a strong JWT secret (REQUIRED):
python -c "import secrets; print(secrets.token_hex(32))"
# Copy the output and set it as NEXUS_AUTH__JWT_SECRET in .env
```

---

## Step 3: Run Database Migrations

```bash
uv run alembic upgrade head
```

---

## Step 4: Seed Demo Data (Optional, for Testing)

```bash
docker exec -i docker-postgres-1 psql -U nexus -d nexus < scripts/seed.sql
```

This creates:
- A demo tenant (`11111111-1111-4111-8111-111111111111`)
- An admin user (`admin@demo.com`)
- 3 tools: `echo`, `create_draft`, `publish_draft`

---

## Step 5: Start the Server

```bash
# Linux / macOS / WSL2 (with AsyncPostgresSaver):
uv run uvicorn nexus.main:create_app --factory --workers 1 --host 0.0.0.0 --port 8000

# Windows (falls back to MemorySaver — same command):
uv run uvicorn nexus.main:create_app --factory --workers 1 --host 0.0.0.0 --port 8000
```

**Verify:**

```bash
curl http://localhost:8000/healthz
# {"status":"ok","version":"0.1.0"}

curl http://localhost:8000/readyz
# {"status":"ok","database":"ok","redis":"ok"}
```

---

## Step 6: Send a Chat Message

```bash
curl -X POST http://localhost:8000/api/v1/sessions/11111111-1111-4111-8111-111111111111/chat \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: 11111111-1111-4111-8111-111111111111" \
  -d '{"message": "Hello! What can you do?", "stream": false}'
```

For SSE streaming (real-time events):

```bash
curl -X POST http://localhost:8000/api/v1/sessions/11111111-1111-4111-8111-111111111111/chat \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: 11111111-1111-4111-8111-111111111111" \
  -d '{"message": "List all tools available", "stream": true}'
```

---

## Step 7: Run the Tests

```bash
# Unit tests (no infrastructure needed)
uv run pytest -m "not slow and not integration and not eval"

# Integration tests (requires PostgreSQL + Redis running)
uv run pytest -m integration

# Full suite
uv run pytest
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `/readyz` shows `database: error` | PostgreSQL not running | `docker compose up -d postgres` |
| `/readyz` shows `redis: error` | Redis not running | `docker compose up -d redis` |
| `No provider found for model` | LLM provider not configured | Set `NEXUS_LLM__DEFAULT_PROVIDER` and corresponding API key |
| `JWT secret is weak or missing` | Missing `NEXUS_AUTH__JWT_SECRET` | Generate one: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `column "metadata" does not exist` | Stale checkpoint tables | `docker exec docker-postgres-1 psql -U nexus -d nexus -c "DROP TABLE IF EXISTS checkpoint_migrations, checkpoint_writes, checkpoint_blobs, checkpoints CASCADE"` then restart server |
| Chat returns `HumanMessage` error | Old code | `git pull` and restart server |
| Connection refused on port 8000 | Server not running | Check server terminal for errors |
| Ollama connection refused | Ollama not running | `ollama serve` |

---

## What's Next

| Guide | Description |
|-------|-------------|
| [Architecture](architecture.md) | System design, data flow, ADRs |
| [Tool Registration](tool-registration.md) | Register your own tools |
| [Integration Guide](integration-guide.md) | Embed the chatbot, SSE/WS client code |
| [HITL Guide](hitl.md) | Human-in-the-loop approval flows |
| [API Reference](api-reference.md) | All endpoints with examples |
| [Operations Guide](operations.md) | Deployment, scaling, monitoring |
