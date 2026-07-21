# Nexus Agent Platform

Open-source AI agent orchestration — plan, execute, and observe tool-calling agents.

| Component | Location | Stack |
|-----------|----------|-------|
| **Backend** | [`nexus-agent/`](nexus-agent/) | Python 3.12, FastAPI, LangGraph, PostgreSQL, Redis |
| **Frontend** | [`frontend/`](frontend/) | React 19, TypeScript, Tailwind CSS v4, shadcn/ui, Vite |

---

## Quick Start

### Docker (all platforms)
```bash
docker compose -f nexus-agent/docker/docker-compose.yml --profile ollama up -d
open http://localhost:5173
```

### Native Development

```bash
cd nexux-agent
uv sync
cd ../frontend && npm install && cd ../
cp nexus-agent/.env.example nexus-agent/.env
docker compose -f nexus-agent/docker/docker-compose.yml up -d postgres redis
cd nexus-agent && uv run alembic upgrade head
uv run python scripts/seed.py
make dev
```

---

## Project Structure

```
nexus-agent/              # Python backend
  src/nexus/
    agent/                # LangGraph orchestration
    api/                  # API endpoints (tools, sessions, chat, approvals)
    llm/                  # LLM client (LiteLLM)
    tools/                # Tool registry, discovery, execution
    config/               # Pydantic settings

frontend/                 # React frontend
  src/
    routes/               # Page components organized by feature
    components/           # Shared components
      ui/                 # shadcn/ui primitives
      layout/             # Sidebar, TopNav, DashboardLayout
    hooks/                # Custom React hooks
    stores/               # Zustand stores
    lib/                  # Utilities, API client
    types/                # TypeScript interfaces
```

## Tech Stack

- **Frontend**: React 19, TypeScript, Tailwind CSS v4, shadcn/ui, TanStack Query, Zustand, React Router v6, recharts, sonner, lucide-react
- **Backend**: Python 3.12, FastAPI, LangGraph, PostgreSQL (pgvector), Redis, LiteLLM

## Features

- **Tools** — Register, manage, search, and test API tools
- **Chat** — Conversational AI with streaming responses, tool calls, and approval workflows
- **Sessions** — Conversation history with context management
- **Approvals** — Human-in-the-loop tool call approval
- **Memory** — Long-term episodic, semantic, and procedural memory

See [`nexus-agent/README.md`](nexus-agent/README.md) for detailed backend documentation.
