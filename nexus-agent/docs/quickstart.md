# Quickstart — Nexus Agent

## Prerequisites (WSL2 Ubuntu)

```bash
# 1. Python 3.12+
python3 --version  # Must be 3.12+

# 2. Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Docker Desktop (for PostgreSQL + Redis)
#    Install from https://www.docker.com/products/docker-desktop/
#    Ensure WSL2 backend is enabled in Docker Desktop settings
```

## Setup (5 minutes)

```bash
# 1. Clone and enter the repo
cd ~
git clone <repo-url> nexus-agent
cd nexus-agent

# 2. Create virtual environment and install dependencies
uv venv
source .venv/bin/activate
uv sync

# 3. Copy environment template
cp .env.example .env
# Edit .env to set:
#   NEXUS_LLM__DEFAULT_MODEL="gpt-4o"    # or any LiteLLM-supported model
#   OPENAI_API_KEY="sk-..."               # your API key

# 4. Start infrastructure (PostgreSQL + Redis)
docker compose -f docker/docker-compose.yml up -d
sleep 5  # Wait for DB initialization

# 5. Run database migrations
uv run alembic upgrade head

# 6. Seed registry (22 tools → capabilities/providers/endpoints)
uv run python scripts/seed_registry.py

# 7. Compile registry offline
uv run python -m nexus.compiler.registry_compiler --output compiled_registry.json

# 8. Verify compiled graph
uv run python -c "
from nexus.compiler.compiled_graph import load_compiled_graph
g = load_compiled_graph()
print(f'Nodes: {len(g.nodes)}, Templates: {len(g.goal_templates)}')
print(f'Cycles: {g.cycles}, Missing producers: {len(g.missing_producers)}')
"
```

## Run

### Terminal 1 — Mock API Server (bookmark/echo tools)

```bash
cd ~/nexus-agent
source .venv/bin/activate
uv run uvicorn scripts.web_search_server:app --host 0.0.0.0 --port 8081 --log-level error
```

### Terminal 2 — Backend Server

```bash
cd ~/nexus-agent
source .venv/bin/activate
uv run uvicorn nexus.main:create_app --factory --host 0.0.0.0 --port 8000 --reload
```

## Test

```bash
# Single tool — Pikachu
SID=$(curl -s -X POST http://localhost:8000/api/v1/sessions \
  -H 'Content-Type: application/json' -d '{}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
curl -s -N -X POST "http://localhost:8000/api/v1/sessions/$SID/chat" \
  -H 'Content-Type: application/json' \
  -d '{"message":"Tell me about Pikachu"}' | grep -E 'event: (final_response|done)'

# Multi-tool chain — Weather + Books
SID2=$(curl -s -X POST http://localhost:8000/api/v1/sessions \
  -H 'Content-Type: application/json' -d '{}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
curl -s -N -X POST "http://localhost:8000/api/v1/sessions/$SID2/chat" \
  -H 'Content-Type: application/json' \
  -d '{"message":"Find weather in Tokyo and suggest books about Japanese culture"}' | grep -E 'event: (final_response|done)'

# Compiler tests
uv run pytest tests/test_compiler_e2e.py -v

# All available tests
uv run pytest
```

## Common Commands

```bash
# Re-seed registry (replaces all data)
uv run python scripts/seed_registry.py

# Re-compile
uv run python -m nexus.compiler.registry_compiler --output compiled_registry.json

# Full clean and re-seed
uv run python -c "
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from nexus.config.settings import get_settings
s=get_settings(); e=create_async_engine(s.database.url.replace('+asyncpg','+psycopg'))
async def run():
    async with AsyncSession(e) as sess:
        await sess.execute(text('TRUNCATE goal_template, endpoint, provider, capability, registry_version CASCADE'))
        await sess.commit(); print('Cleaned')
    await e.dispose()
asyncio.run(run())
"
uv run python scripts/seed_registry.py
uv run python -m nexus.compiler.registry_compiler --output compiled_registry.json

# Cache invalidation (after re-compilation)
curl -s -X POST http://localhost:8000/api/v1/registry/invalidate-cache
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `Connection refused` on port 5432 | PostgreSQL not started: `docker compose -f docker/docker-compose.yml up -d` |
| `Connection refused` on port 8081 | Mock server not started: `uv run uvicorn scripts.web_search_server:app --port 8081` |
| `alembic upgrade head` fails | Check database URL in `.env` — ensure PostgreSQL is running |
| Compiler returns `0 nodes` | Registry not seeded: `uv run python scripts/seed_registry.py` |
| Tests timeout (120s+) | LLM API may be slow. Increase `NEXUS_LLM_TIMEOUT` or check API key |
| Agent says "I couldn't determine" | Intent not recognized. Check `available_intents` or try a different phrasing |
