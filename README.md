# Nexus Agent Platform

Open-source AI agent orchestration — plan, execute, and observe tool-calling agents.

| Component | Location | Stack |
|-----------|----------|-------|
| **Backend** | [`nexus-agent/`](nexus-agent/) | Python 3.12, FastAPI, LangGraph, PostgreSQL, Redis |
| **Frontend** | [`frontend/`](frontend/) | React 19, TypeScript, Tailwind CSS v4, shadcn/ui, Vite |

---

## Architecture (Windows + WSL2)

```
Windows Host
  ├── Frontend (Vite dev server)      → localhost:5173
  │     └── Proxies /api → WSL2 backend
  ├── PostgreSQL 16 + pgvector (Docker) → host.docker.internal:5433
  ├── Redis 7 (Docker)                 → host.docker.internal:6379
  └── Ollama (LLM models)             → localhost:11434 (OLLAMA_HOST=0.0.0.0)

WSL2 Ubuntu
  └── Backend (uvicorn + FastAPI)     → 0.0.0.0:8000
        └── Connects to:
              PostgreSQL → 172.27.160.1:5433 (Windows host)
              Redis      → 172.27.160.1:6379 (Windows host)
              Ollama     → 172.27.160.1:11434 (Windows host)
```

**Network note:** WSL2 gets a dynamic IP (typically `172.27.x.x`). The Windows host is accessible from WSL2 at the gateway IP (typically `172.27.160.1`). Find yours with: `wsl -d Ubuntu ip route show default`

---

## Quick Start (Windows + WSL2)

### Prerequisites

| Tool | Install |
|------|---------|
| **WSL2 Ubuntu** | `wsl --install -d Ubuntu` |
| **Docker Desktop** | [docker.com](https://www.docker.com/products/docker-desktop/) — enable WSL2 integration |
| **Python 3.12+** | On WSL2: `sudo apt install python3.12 python3.12-venv` |
| **uv** | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Node.js 20+** | [nodejs.org](https://nodejs.org/) |
| **Ollama** | [ollama.com](https://ollama.com/) — required for local embeddings |

### Step 1: Start Infrastructure (Windows)

```powershell
# Start Docker services (PostgreSQL + Redis)
docker compose -f nexus-agent/docker/docker-compose.yml up -d postgres redis

# Start Ollama (for embedding model nomic-embed-text)
set OLLAMA_HOST=0.0.0.0
ollama serve

# In another terminal, pull the embedding model
ollama pull nomic-embed-text
```

### Step 2: Setup Backend (WSL2)

```bash
# Open WSL2 terminal
wsl -d Ubuntu

# Clone and setup
cd ~
git clone <your-repo-url> nexus-agent
cd nexus-agent
uv sync
cp nexus-agent/.env nexus-agent/.env.local

# Edit .env.local if needed — the defaults point to Windows host at 172.27.160.1
# Find your Windows IP:
WSL_GATEWAY=$(ip route show default | awk '{print $3}')
echo "Windows host: $WSL_GATEWAY"

# Run DB migrations
cd nexus-agent && uv run alembic upgrade head

# Start the backend server
uv run uvicorn nexus.main:app --host 0.0.0.0 --port 8000
```

### Step 3: Start Frontend (Windows)

```powershell
# In a separate Windows terminal (PowerShell or cmd)
cd frontend
npm install
npm run dev
```

### Step 4: Test

```bash
# From Windows: check backend health
curl http://localhost:5173/api/healthz

# Or from WSL2: check directly
curl http://localhost:8000/healthz
```

Open **http://localhost:5173** in your browser.

---

## Project Structure

```
nexus-agent/              # Python backend (runs on WSL2)
  src/nexus/
    agent/                # LangGraph orchestration
    api/                  # API endpoints (tools, sessions, chat, approvals)
    llm/                  # LLM client (LiteLLM)
    tools/                # Tool registry, discovery, execution
    config/               # Pydantic settings

frontend/                 # React frontend (runs on Windows)
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
- **Orchestration**: LangGraph StateGraph with 6 parent nodes + 3-node tool subgraph
- **LLM Providers**: NVIDIA NIM (primary), Ollama (local embeddings), OpenRouter (fallback)

## Features

- **Tools** — Register, manage, search, and test API tools (GET/POST/PUT/PATCH/DELETE)
- **Chat** — Conversational AI with streaming responses, tool calls, and approval workflows
- **Sessions** — Conversation history with context management
- **Approvals** — Human-in-the-loop tool call approval
- **Memory** — Long-term episodic, semantic, and procedural memory with pgvector search
- **Dynamic Prompts** — Query complexity detection switches between short and full thinking protocols
- **Observability** — LangSmith tracing for every LLM call and node execution

## Performance Optimizations

| Optimization | Speed Impact | Location |
|---|---|---|
| Greeting template (no LLM) | **~9ms** vs 3s | `respond_without_tool.py` |
| Single-tool fast path | **~5ms** vs 1-5s | `dag_expander.py` |
| Tool schema pruning | **60% smaller prompts** | `dag_expander.py` |
| Memory in background | **Response not blocked** | `finalize.py` |
| Tool cache (60s TTL) | **No DB per request** | `runner.py` |
| Embedding cache (1h TTL) | **No re-embed on repeat** | `registry.py` |

See [`nexus-agent/AGENTS.md`](nexus-agent/AGENTS.md) for detailed node documentation.

---

## Troubleshooting (Windows + WSL2)

### "Connection refused" from frontend to backend
```powershell
# Get the WSL2 IP and update frontend proxy
wsl -d Ubuntu hostname -I
# Update frontend/vite.config.ts → target: "http://<WSL2-IP>:8000"
```

### "QueuePool limit exceeded"
```powershell
# Restart the backend server on WSL2
wsl -d Ubuntu -c "pkill -f uvicorn; sleep 2; cd ~/nexus-agent && uv run uvicorn nexus.main:app --host 0.0.0.0 --port 8000 &"
```

### Ollama connection timeout
```powershell
# Ensure Ollama listens on all interfaces
set OLLAMA_HOST=0.0.0.0
ollama serve
# From WSL2, verify:
wsl -d Ubuntu curl -s http://172.27.160.1:11434/api/tags
```

### Model not responding
```powershell
# Check NVIDIA NIM API key
wsl -d Ubuntu -c "grep NVIDIA_NIM_API_KEY ~/nexus-agent/.env"
# Test direct:
wsl -d Ubuntu -c "cd ~/nexus-agent && source .venv/bin/activate && python -c 'import asyncio,litellm; print(asyncio.run(litellm.acompletion(model=\"nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b\", messages=[{\"role\":\"user\",\"content\":\"Hi\"}], max_tokens=10)))'"
```

---

See [`nexus-agent/README.md`](nexus-agent/README.md) for detailed backend documentation.
