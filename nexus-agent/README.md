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
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐           │
│  │  AuthN/Z │  │  Rate    │  │  Structured  │           │
│  │Middleware│  │ Limiter  │  │   Logging    │           │
│  └──────────┘  └──────────┘  └──────────────┘           │
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
│              Data Layer (Single-Tenant)                     │
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
| `NEXUS_DATABASE__POOL_SIZE` | No | `10` | Connection pool size |
| `NEXUS_REDIS__URL` | Yes | — | Redis connection string (`redis://...`) |
| | | | |
| **LLM** | | | |
| `NEXUS_LLM__DEFAULT_PROVIDER` | No | `openai` | LiteLLM provider name |
| `NEXUS_LLM__DEFAULT_MODEL` | No | `gpt-4o` | Model identifier (e.g. `gpt-4o`, `claude-sonnet-4-20250514`, `deepseek/deepseek-chat`) |
| `NEXUS_LLM__PROVIDERS` | No | — | JSON array of provider configs (see `.env.example`) |
| `NEXUS_LLM__EMBEDDING_MODEL` | No | `text-embedding-3-small` | Model for generating embeddings |
| `NEXUS_LLM__EMBEDDING_DIMENSIONS` | No | `768` | Output dimension for embedding vectors (must match DB column) |
| | | | |
| **Memory** | | | |
| `NEXUS_MEMORY__ENABLED` | No | `true` | Enable memory extraction |
| `NEXUS_MEMORY__RETRIEVAL_TOP_K` | No | `5` | Memories per query |
| | | | |
| **Agent** | | | |
| `NEXUS_AGENT__HITL_DEFAULT` | No | `true` | Require human approval by default |
| `NEXUS_AGENT__RUN_LOCK_TTL_S` | No | `600` | Per-session lock TTL in seconds |
| `NEXUS_TOOLS__MAX_RETRIES` | No | `3` | Max retries per tool call |
| `NEXUS_SERVER__WORKERS` | No | `4` | Number of uvicorn workers |
| | | | |
| **Logging** | | | |
| `NEXUS_ENV` | No | `development` | Environment name |
| `NEXUS_LOG_LEVEL` | No | `INFO` | Log level |
| `NEXUS_LOG_FORMAT` | No | `console` | Log format (`console` or `json`) |

> **Using a non-OpenAI provider?** LiteLLM supports 100+ providers. Set
> `NEXUS_LLM__DEFAULT_PROVIDER` and `NEXUS_LLM__DEFAULT_MODEL` with the
> correct prefix for your provider:
>
> | Provider | Model prefix | Env Var |
> |----------|-------------|---------|
> | Ollama (local) | `ollama/qwen2.5:7b` | *(none)* |
> | DeepSeek | `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` |
> | Anthropic | `claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` |
> | OpenRouter | `openrouter/...` | `OPENROUTER_API_KEY` |
> | Groq | `groq/llama3-70b-8192` | `GROQ_API_KEY` |
> | Google Gemini | `gemini/gemini-2.0-flash` | `GEMINI_API_KEY` |
>
> See [LiteLLM Providers](https://docs.litellm.ai/docs/providers) for the
> full list of 100+ supported providers and their required env vars.
>
> For a complete setup guide, see [docs/quickstart.md](docs/quickstart.md).

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
