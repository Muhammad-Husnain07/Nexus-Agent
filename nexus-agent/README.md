# Nexus Agent — Compiler-Inspired Agentic AI Orchestration

A **standalone, vendor-neutral agentic AI orchestration layer** that transforms natural language into a 4-layer Intermediate Representation (Intent → Goal → Operation → Execution) via an **offline-to-runtime pipeline**. All ontology, schema validation, and capability graph generation happens at **compile time**. The runtime is a lean, deterministic executor.

**Zero business logic.** The AI is a pure orchestration brain that delegates all domain work to registered tools.

---

## Architecture at a Glance

```
┌──────────────────────────────────────────────────────────────┐
│   Offline (compile time)         │    Runtime (online)        │
│   ┌──────────────────┐          │  ┌──────────────────────┐  │
│   │  Registry Compiler │───────►│  │  Compiled Graph       │  │
│   │  nexus compile     │         │  │  (immutable, pre-built)│  │
│   └──────────────────┘          │  └──────────┬───────────┘  │
│   ┌──────────────────┐          │             │               │
│   │  4 Seed Scripts   │         │  ┌──────────▼───────────┐  │
│   │  (22 tools →      │         │   │  LangGraph (13 nodes)  │  │
│   │   capabilities)   │         │  │  @context_node enforces│  │
│   └──────────────────┘          │  │  Context(v)→Context(v+1)│ │
│                                 │  └──────────┬───────────┘  │
│   ┌──────────────────┐          │             │               │
│   │  Passes (plugins) │         │  ┌──────────▼───────────┐  │
│   │  dynamically       │         │  │  Plugin Pass Manager  │  │
│   │  discovered        │         │  │  (4 optimizer passes)  │  │
│   └──────────────────┘          │  └──────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

---

## Quickstart (WSL2)

### Prerequisites

- **Windows 11** with WSL2 (Ubuntu 24.04 recommended)
- **Python 3.12+** and **[uv](https://docs.astral.sh/uv/)**
- **Docker Desktop** with WSL2 backend (for PostgreSQL + Redis)

### Step-by-Step Setup

```bash
# 1. Inside WSL2 Ubuntu
cd ~
git clone <repo-url> nexus-agent
cd nexus-agent

# 2. Create virtual environment
uv venv
source .venv/bin/activate
uv sync

# 3. Copy environment template
cp .env.example .env
# Edit .env to set NEXUS_LLM__DEFAULT_MODEL and your API keys

# 4. Start infrastructure
docker compose -f docker/docker-compose.yml up -d
# Wait 5 seconds for PostgreSQL + Redis to initialize

# 5. Run migrations
uv run alembic upgrade head

# 6. Seed the registry (22 tools → capabilities/providers/endpoints)
uv run python scripts/seed_registry.py

# 7. Compile the registry offline
uv run python -m nexus.compiler.registry_compiler --output compiled_registry.json

# 8. Start the mock API proxy (for bookmark/echo tools) in a separate terminal
#    This must run on port 8081
uv run uvicorn scripts.web_search_server:app --host 0.0.0.0 --port 8081 --log-level error

# 9. Start the backend (in a separate terminal)
uv run uvicorn nexus.main:create_app --factory --host 0.0.0.0 --port 8000 --reload

# 10. Run all tests
uv run pytest
```

### Using tmux (Single Terminal)

```bash
# Install tmux
sudo apt install -y tmux

# Create a session that starts everything
cat > ~/start-nexus.sh << 'EOF'
#!/bin/bash
cd ~/nexus-agent
tmux new-session -d -s nexus -n "services"
tmux send-keys -t nexus "docker compose -f docker/docker-compose.yml up -d" Enter
sleep 5
tmux split-window -h -t nexus
tmux send-keys -t nexus "uv run alembic upgrade head" Enter
tmux send-keys -t nexus "uv run python scripts/seed_registry.py" Enter
tmux send-keys -t nexus "uv run python -m nexus.compiler.registry_compiler --output compiled_registry.json" Enter
tmux new-window -t nexus -n "proxy"
tmux send-keys -t nexus "uv run uvicorn scripts.web_search_server:app --host 0.0.0.0 --port 8081 --log-level error" Enter
tmux new-window -t nexus -n "backend"
tmux send-keys -t nexus "uv run uvicorn nexus.main:create_app --factory --host 0.0.0.0 --port 8000 --reload" Enter
EOF
chmod +x ~/start-nexus.sh
~/start-nexus.sh

# Attach to view logs
tmux attach -t nexus

# Kill everything
tmux kill-session -t nexus
docker compose -f docker/docker-compose.yml down
```

### Testing the Agent

```bash
# Create a session and send a message
SID=$(curl -s -X POST http://localhost:8000/api/v1/sessions \
  -H 'Content-Type: application/json' -d '{}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Ask about Pikachu (single tool)
curl -s -N -X POST "http://localhost:8000/api/v1/sessions/$SID/chat" \
  -H 'Content-Type: application/json' \
  -d '{"message":"Tell me about Pikachu"}'

# Multi-tool chain
curl -s -N -X POST "http://localhost:8000/api/v1/sessions/$SID/chat" \
  -H 'Content-Type: application/json' \
  -d '{"message":"Find weather in Tokyo and search for Japanese culture books"}'
```

---

## Environment Variables

All variables use the `NEXUS_` prefix with `__` as the nested delimiter.
Example: `NEXUS_DATABASE__URL` → `settings.database.url`.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEXUS_DATABASE__URL` | Yes | — | PostgreSQL async connection (`postgresql+asyncpg://nexus:nexus@localhost:5432/nexus`) |
| `NEXUS_REDIS__URL` | Yes | — | Redis connection (`redis://localhost:6379`) |
| `NEXUS_LLM__DEFAULT_MODEL` | Yes | `gpt-4o` | Model identifier (e.g. `deepseek/deepseek-chat`, `claude-sonnet-4-20250514`) |
| `NEXUS_LLM__DEFAULT_PROVIDER` | No | `openai` | LiteLLM provider name |
| `NEXUS_AGENT__MAX_REFLECTION_RETRIES` | No | `0` | Max retry cycles per turn (set to 0 to disable retry loop) |
| `NEXUS_MEMORY__ENABLED` | No | `true` | Enable memory extraction |
| `NEXUS_SERVER__WORKERS` | No | `4` | Number of uvicorn workers |

### LLM Provider Examples

| Provider | Model | Required Env Var |
|----------|-------|-----------------|
| OpenAI | `gpt-4o` | `OPENAI_API_KEY` |
| DeepSeek | `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` |
| Anthropic | `claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` |
| Ollama (local) | `ollama/qwen2.5:7b` | *(none)* |
| NVIDIA NIM | `nvidia/nemotron-3-ultra-550b-a55b` | `NVIDIA_API_KEY` |

---

## Project Structure

```
nexus-agent/
├── alembic/                 # DB migrations (6 registry tables)
├── docs/                    # Documentation
├── scripts/                 # Seed data, test runners, utilities
│   ├── seed_registry.py     # Populates capability/provider/endpoint from tools
│   ├── web_search_server.py # Mock bookmark/echo API proxy (port 8081)
│   └── seed.sql             # Initial tool seed data
├── src/nexus/
│   ├── agent/               # LangGraph 19-node graph (intent-first) + @context_node
│   │   ├── nodes/           # 19 production nodes + prompt files
│   │   ├── planners/        # Thin DAG planner shim → Compiler
│   │   ├── executors/       # ConcurrentExecutor with per-domain concurrency
│   │   ├── node_wrapper.py  # @context_node decorator
│   │   └── state_schema.py  # AgentState with _ir_stack, _context_version
│   ├── api/                 # FastAPI routes, SSE streaming, middleware
│   ├── compiler/            # Logical/Physical IR, resolver, codegen, cache, pass manager
│   │   ├── passes/          # 6 optimization passes (dynamic discovery)
│   │   ├── ir_models.py     # LogicalNode → ToolNode/MapNode/ReduceNode/ConditionalNode
│   │   ├── cache.py         # ParseCache + PlanCache with stats
│   │   ├── pass_manager.py  # LLVM-style pass manager
│   │   ├── registry_compiler.py  # Offline compiler + CLI
│   │   └── compiled_graph.py     # Runtime reader with DB fallback
│   ├── config/              # Pydantic BaseSettings
│   ├── db/models/           # SQLAlchemy ORM models (+ 6 registry tables)
│   ├── execution/           # ExecutionContext, StatePatch, EventStore
│   ├── graph/               # KnowledgeGraph (8 specialized graphs)
│   ├── llm/                 # LiteLLM integration
│   ├── memory/              # PostgresSaver + MemoryStore (pgvector)
│   ├── metrics/             # EWMA reliability store
│   ├── middleware/          # Custom ASGI middleware
│   ├── redis_client/        # Redis cache & pub/sub
│   ├── security/            # AuthN/Z helpers
│   ├── sessions/            # Session lifecycle
│   ├── tools/               # MCP client + ToolRegistry
│   └── utils/               # Shared utilities
├── tests/
│   ├── test_compiler_e2e.py # 23 compiler tests (IR, context, cache, passes, EWMA)
│   └── test_ephemeral_fields.py  # Ephemeral fields drift test
├── AGENTS.md                # Developer & AI coding guide
├── pyproject.toml           # Python project config (+ nexus CLI)
└── README.md                # This file
```

---

## Compiler Commands

```bash
# Compile the registry (offline)
uv run python -m nexus.compiler.registry_compiler --output compiled_registry.json

# Seed the registry from tools
uv run python scripts/seed_registry.py

# Clear and re-seed (for development)
uv run python -c "
import asyncio; from sqlalchemy import text; from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession;
from nexus.config.settings import get_settings; s=get_settings(); e=create_async_engine(s.database.url.replace('+asyncpg','+psycopg'))
async def run():
    async with AsyncSession(e) as sess:
        await sess.execute(text('TRUNCATE goal_template, endpoint, provider, capability, registry_version CASCADE'))
        await sess.commit(); print('Cleaned')
    await e.dispose()
asyncio.run(run())
"
```

---

## Running the Full 25-Test Battery

```bash
# Start all services
docker compose -f docker/docker-compose.yml up -d
uv run uvicorn scripts.web_search_server:app --host 0.0.0.0 --port 8081 --log-level error &
uv run uvicorn nexus.main:create_app --factory --host 0.0.0.0 --port 8000 --reload &

# Run compiler tests
uv run pytest tests/test_compiler_e2e.py -v

# Run ephemeral fields drift test
uv run pytest tests/test_ephemeral_fields.py -v

# Run all available tests
uv run pytest
```

---

## Documentation

- **[AGENTS.md](AGENTS.md)** — Full 10-phase compiler architecture, coding standards, conventions
- **[docs/architecture.md](docs/architecture.md)** — Detailed architecture, data flows, ADRs, deployment guide
- **[src/nexus/agent/AGENTS.md](src/nexus/agent/AGENTS.md)** — 19-node graph details, routing functions, state schema, P4 validation

---

## License

Proprietary — All rights reserved.
