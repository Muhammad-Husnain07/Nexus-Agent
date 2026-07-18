# Nexus Agent Platform

| Component | Location | Tech |
|-----------|----------|------|
| **Backend** | [`nexus-agent/`](nexus-agent/) | Python 3.12, FastAPI, LangGraph, PostgreSQL |
| **Frontend** | [`frontend/`](frontend/) | React 18, Vite, TypeScript, shadcn/ui |

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
cd frontend
npm install
npm run dev
```

See [`nexus-agent/README.md`](nexus-agent/README.md) for detailed backend docs.
