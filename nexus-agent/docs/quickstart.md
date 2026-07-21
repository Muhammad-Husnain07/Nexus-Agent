# Quickstart

## Prerequisites

- Python 3.12+
- Node.js 20+
- Docker (for PostgreSQL + Redis)
- uv (recommended)

## Setup

```bash
# Clone
git clone <repo> && cd nexus-agent

# Backend
cd nexus-agent
uv sync
cp .env.example .env

# Start infrastructure
docker compose -f docker/docker-compose.yml up -d postgres redis

# Run migrations
uv run alembic upgrade head

# Seed demo tools
uv run python scripts/seed.py

# Start backend
uv run uvicorn nexus.main:create_app --factory --reload --host 0.0.0.0 --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

## LLM Provider Setup

Set the following in `.env`:

### Ollama (local)
```
NEXUS_LLM__DEFAULT_PROVIDER=ollama
NEXUS_LLM__DEFAULT_MODEL=ollama/qwen2.5:7b
```

### OpenAI
```
NEXUS_LLM__DEFAULT_PROVIDER=openai
NEXUS_LLM__DEFAULT_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-...
```

## Project Structure

```
nexus-agent/
  src/nexus/
    agent/       LangGraph orchestration
    api/         FastAPI routes
    llm/         LiteLLM client
    tools/       Tool registry & execution
    config/      Settings
  scripts/
    seed.py      Seed demo tools
    setup.py     Interactive wizard
frontend/
  src/
    routes/      Page components
    components/  UI components
    hooks/       React hooks
    lib/         API client
```
