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
uv run uvicorn src.nexus.main:create_app --factory --reload
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | PostgreSQL async connection string (`postgresql+asyncpg://...`) |
| `REDIS_URL` | Yes | — | Redis connection string (`redis://...`) |
| `LLM_API_KEY` | Yes | — | API key for default LLM provider |
| `LLM_MODEL` | No | `gpt-4o` | Default LLM model identifier |
| `LLM_PROVIDER` | No | `openai` | LiteLLM provider name |
| `LANGCHAIN_API_KEY` | No | — | LangSmith API key (tracing) |
| `NEXUS_LOG_LEVEL` | No | `INFO` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `NEXUS_MAX_TOOL_RETRY` | No | `3` | Max retries per tool call |
| `NEXUS_HITL_DEFAULT` | No | `true` | Require human approval by default |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | No | — | OpenTelemetry collector endpoint |

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
