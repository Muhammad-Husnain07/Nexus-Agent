# Nexus Agent Platform

| Component | Location | Tech |
|-----------|----------|------|
| **Backend** | [`nexus-agent/`](nexus-agent/) | Python 3.12, FastAPI, LangGraph, PostgreSQL |
| **Frontend** | [`nexus-console/`](nexus-console/) | React 19, TypeScript, MUI v9, Vite |

## Quickstart

### Backend
```bash
cd nexus-agent
uv sync
cp .env.example .env
docker compose -f docker/docker-compose.yml up -d postgres redis
uv run alembic upgrade head
uv run uvicorn nexus.main:create_app --factory --reload
```

### Frontend
```bash
cd nexus-console
npm install
npm run dev
```

### Docker (full stack)
```bash
docker compose -f nexus-agent/docker/docker-compose.yml up -d
```

See [`nexus-agent/README.md`](nexus-agent/README.md) for detailed backend docs.
