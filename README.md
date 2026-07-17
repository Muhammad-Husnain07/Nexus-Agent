# Nexus Agent

A **standalone, vendor-neutral agentic AI orchestration layer** that exposes a conversational AI to plan, reason, gather requirements, and invoke application capabilities via registered tools. The AI contains **zero business logic** — it is a pure orchestration brain.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     Clients (API / WebSocket / SSE)       │
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│                    FastAPI Gateway                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │ AuthN/Z  │ │  Tenant  │ │  Rate    │ │  Structured  │ │
│  │Middleware │ │Extract   │ │ Limiter  │ │   Logging    │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘ │
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│                 LangGraph Agent Graph                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐│
│  │  LLM     │  │  Memory  │  │  HITL    │  │ Session   ││
│  │ (LiteLLM)│  │ (Redis+PG)│  │  Gate    │  │ Manager   ││
│  └──────────┘  └──────────┘  └──────────┘  └───────────┘│
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│                   Tool Layer (MCP + Registry)              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐│
│  │  MCP Client  │  │  ToolRegistry │  │  Execution       ││
│  │  (discover)  │  │  (register)   │  │  (invoke/audit)  ││
│  └──────────────┘  └──────────────┘  └──────────────────┘│
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│              Data Layer (Multi-Tenant)                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐│
│  │PostgreSQL│  │ pgvector │  │  Redis   │  │   Object  ││
│  │+asyncpg  │  │ (embeds) │  │  (cache) │  │   Store   ││
│  └──────────┘  └──────────┘  └──────────┘  └───────────┘│
└──────────────────────────────────────────────────────────┘
```

---

## Quickstart

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker & Docker Compose (for PostgreSQL + Redis)

### Setup

```bash
# Clone and enter the repo
git clone <repo-url> && cd nexus-agent

# Create virtual environment and install dependencies
uv venv
uv sync

# Copy env template
cp .env.example .env

# Start infrastructure
docker compose -f docker/docker-compose.yml up -d

# Run database migrations
uv run alembic upgrade head

# Start the development server
uv run uvicorn nexus.main:create_app --factory --reload
```

### Environment Variables

All variables use the `NEXUS_` prefix with `__` as the nested group delimiter.
Example: `NEXUS_DATABASE__URL` sets `settings.database.url`.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEXUS_DATABASE__URL` | Yes | — | PostgreSQL async connection string (`postgresql+asyncpg://...`) |
| `NEXUS_DATABASE__POOL_SIZE` | No | `10` | Connection pool size |
| `NEXUS_REDIS__URL` | Yes | — | Redis connection string (`redis://...`) |
| `NEXUS_LLM__DEFAULT_PROVIDER` | No | `openai` | LiteLLM provider name |
| `NEXUS_LLM__DEFAULT_MODEL` | No | `gpt-4o` | Model identifier (e.g. `gpt-4o`, `claude-sonnet-4-20250514`, `deepseek/deepseek-chat`) |
| `NEXUS_LLM__PROVIDERS` | No | — | JSON array of provider configs (see `.env.example`) |
| `NEXUS_AUTH__JWT_SECRET` | Yes | — | 32+ char random secret |
| `NEXUS_AGENT__HITL_DEFAULT` | No | `true` | Require human approval by default |
| `NEXUS_AGENT__RUN_LOCK_TTL_S` | No | `600` | Per-session lock TTL in seconds |
| `NEXUS_TOOLS__MAX_RETRIES` | No | `3` | Max retries per tool call |
| `NEXUS_SERVER__WORKERS` | No | `4` | Number of uvicorn workers |
| `NEXUS_OBSERVABILITY__LANGSMITH_API_KEY` | No | — | LangSmith API key for tracing |
| `NEXUS_OBSERVABILITY__LOG_LEVEL` | No | `INFO` | Log level |
| `NEXUS_OBSERVABILITY__OTEL_ENDPOINT` | No | — | OpenTelemetry collector endpoint |

> **Using a non-OpenAI provider?** Set `NEXUS_LLM__DEFAULT_PROVIDER` to your provider
> name and `NEXUS_LLM__DEFAULT_MODEL` to the model identifier. Export the
> corresponding API key (e.g. `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `GEMINI_API_KEY`).
> LiteLLM handles routing automatically. See [LiteLLM providers docs](https://docs.litellm.ai/docs/providers).

### Docker Compose

```bash
# Start all services
docker compose -f docker/docker-compose.yml up --build

# Background mode
docker compose -f docker/docker-compose.yml up -d

# View logs
docker compose -f docker/docker-compose.yml logs -f

# Stop everything
docker compose -f docker/docker-compose.yml down
```

---

## Project Structure

```
nexus-agent/
├── .github/workflows/     # CI pipeline
├── alembic/               # Database migrations
├── docker/                # Dockerfile + docker-compose
├── docs/                  # Architecture & design docs
├── examples/              # Usage examples
├── scripts/               # Utility scripts
├── src/nexus/             # Application source
│   ├── agent/             # LangGraph orchestration graph
│   ├── api/               # FastAPI routes & middleware
│   ├── config/            # Pydantic BaseSettings
│   ├── db/                # SQLAlchemy models & session
│   ├── errors/            # Exception hierarchy
│   ├── llm/               # LiteLLM integration
│   ├── memory/            # Short-term & long-term memory
│   ├── middleware/         # Custom ASGI middleware
│   ├── observability/     # OpenTelemetry + structlog
│   ├── redis_client/      # Redis cache & pub/sub
│   ├── security/          # AuthN/Z helpers
│   ├── sessions/          # Session lifecycle
│   ├── tools/             # MCP client + ToolRegistry
│   └── utils/             # Shared utilities
├── tests/                 # Test suites
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   └── evals/
├── AGENTS.md              # Developer & AI coding guide
├── pyproject.toml         # Python project config
└── README.md              # This file
```

---

## Documentation

- **[AGENTS.md](AGENTS.md)** — Locked tech stack, coding standards, conventions, and rules for both human and AI developers.
- **[docs/architecture.md](docs/architecture.md)** — Detailed architecture documentation and ADRs (to be created).

---

## License

Proprietary — All rights reserved.
