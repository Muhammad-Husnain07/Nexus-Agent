# Nexus Agent Platform

Open-source AI agent orchestration — plan, execute, and observe tool-calling agents.

| Component | Location | Stack |
|-----------|----------|-------|
| **Backend** | [`nexus-agent/`](nexus-agent/) | Python 3.12, FastAPI, LangGraph, PostgreSQL, Redis |
| **Frontend** | [`frontend/`](frontend/) | React 19, TypeScript, Tailwind CSS, Vite |

---

## 🐳 Quick Start — Docker (all platforms)

**Prerequisites:** [Docker Desktop](https://docs.docker.com/get-docker/)

```bash
# Clone the repo
git clone <repo-url> && cd nexus-agent

# Start everything — PostgreSQL, Redis, Ollama, backend, frontend
docker compose -f nexus-agent/docker/docker-compose.yml --profile ollama up -d

# Open the app
open http://localhost:5173
```

Wait ~60s for first-time setup (migrations + model download). Subsequent starts are ~10s.

---

## 💻 Native Development

### Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.12+ | [python.org](https://python.org) |
| Node.js | 20+ | [nodejs.org](https://nodejs.org) |
| Docker | (optional) | [docker.com](https://docker.com) — for PostgreSQL + Redis |
| uv | (recommended) | `pip install uv` or [docs.astral.sh/uv](https://docs.astral.sh/uv/) |

### Linux / macOS

```bash
make setup        # interactive wizard → .env, migrations, seed data
make dev          # starts backend (8000) + frontend (5173)
```

### Windows (PowerShell)

```powershell
.\nexus-agent\scripts\dev.ps1   # auto-installs deps, migrates, seeds, starts both servers
```

### Step by step (any OS)

```bash
cd nexus-agent

# 1. Install dependencies
uv sync
cd ../frontend && npm install && cd ../

# 2. Configure
cp nexus-agent/.env.example nexus-agent/.env
# Edit .env — pick your LLM provider (see table below)

# 3. Start infrastructure (PostgreSQL + Redis)
docker compose -f nexus-agent/docker/docker-compose.yml up -d postgres redis

# 4. Initialize database
cd nexus-agent && uv run alembic upgrade head

# 5. Seed demo tools
uv run python scripts/seed.py --no-embed

# 6. Start servers
uv run uvicorn nexus.main:create_app --factory --reload --port 8000 &   # backend
cd ../frontend && npm run dev                                            # frontend
```

---

## 🤖 LLM Providers

| Provider | Setup | Best for |
|----------|-------|----------|
| **Ollama** (local, free) | Docker profile `--profile ollama` or install separately | Demo, offline |
| **OpenAI** | Set `OPENAI_API_KEY` in `.env` | Production |
| **Gemini** | Set `GEMINI_API_KEY` in `.env` | Speed, free tier |
| **OpenRouter** | Set `OPENROUTER_API_KEY` in `.env` | Multi-model access |

Run `uv run python scripts/setup.py` for an interactive provider configurator.

---

## 📁 Project Structure

```
nexus-agent/              # Python backend
  src/nexus/
    agent/                # LangGraph orchestration graph
    api/                  # FastAPI routes (chat, sessions, tools)
    llm/                  # LLM client — LiteLLM wrapper
    tools/                # Tool registry, discovery, execution
    config/               # Pydantic settings (env-based)
  scripts/
    setup.py              # Interactive setup wizard
    seed.py               # Seed demo tools
    dev.ps1               # Windows dev launcher
  docker/
    docker-compose.yml    # Full stack with profiles

frontend/                 # React frontend
  src/
    features/chat/        # Chat interface
    lib/                  # API client, types
```

## 📚 More

- [Backend documentation](nexus-agent/README.md)
- [Quickstart guide](nexus-agent/docs/quickstart.md)
- [API reference](nexus-agent/docs/api-reference.md)
- [Tool registration](nexus-agent/docs/tool-registration.md)

---

## Common Tasks

```bash
make setup        # Interactive setup wizard
make dev          # Start backend + frontend (Linux/macOS)
make migrate      # Run database migrations
make seed         # Seed demo tools
make lint         # Run linters (ruff)
make test         # Run tests
```

Windows equivalents via `.\nexus-agent\scripts\dev.ps1`.
