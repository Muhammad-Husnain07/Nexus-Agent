# ─── Nexus Agent — Common Tasks ───────────────────────────────────────────────

BACKEND_DIR   = nexus-agent
FRONTEND_DIR  = frontend
PYTHON       := $(shell which python3 2>/dev/null || which python 2>/dev/null)

.PHONY: help setup install-deps infra migrate seed dev backend frontend lint typecheck test clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ─── Setup ────────────────────────────────────────────────────────────────────

setup: ## Full interactive setup (prerequisites → .env → infra → seed)
	@cd $(BACKEND_DIR) && uv run python scripts/setup.py

setup-auto: ## Non-interactive setup (Ollama defaults)
	@cd $(BACKEND_DIR) && uv run python scripts/setup.py --auto

# ─── Dependencies ─────────────────────────────────────────────────────────────

install-deps: ## Install backend and frontend dependencies
	@echo "Installing backend dependencies..."
	cd $(BACKEND_DIR) && uv sync
	@echo "Installing frontend dependencies..."
	cd $(FRONTEND_DIR) && npm install

# ─── Infrastructure ───────────────────────────────────────────────────────────

infra: ## Start PostgreSQL + Redis via Docker
	@echo "Starting infrastructure..."
	docker compose -f $(BACKEND_DIR)/docker/docker-compose.yml up -d postgres redis
	@echo "Waiting for PostgreSQL..."
	@sleep 3

infra-down: ## Stop infrastructure
	docker compose -f $(BACKEND_DIR)/docker/docker-compose.yml down

# ─── Database ─────────────────────────────────────────────────────────────────

migrate: ## Run database migrations
	@cd $(BACKEND_DIR) && uv run alembic upgrade head

seed: ## Seed demo tools into the database
	@cd $(BACKEND_DIR) && uv run python scripts/seed.py --no-embed

seed-full: ## Seed demo tools with embeddings
	@cd $(BACKEND_DIR) && uv run python scripts/seed.py

# ─── Development Servers ─────────────────────────────────────────────────────

backend: ## Start the backend API server (hot-reload)
	@cd $(BACKEND_DIR) && uv run uvicorn nexus.main:create_app --factory --reload --host 0.0.0.0 --port 8000

frontend: ## Start the frontend dev server
	@cd $(FRONTEND_DIR) && npm run dev

dev: ## Start both backend and frontend
	@echo "Starting backend and frontend..."
	@$(MAKE) -j2 backend frontend 2>/dev/null || \
		($(MAKE) backend & $(MAKE) frontend & wait)

# ─── Docker (Full Stack) ──────────────────────────────────────────────────────

docker-up: ## Start everything via Docker Compose
	docker compose -f $(BACKEND_DIR)/docker/docker-compose.yml up -d

docker-down: ## Stop everything
	docker compose -f $(BACKEND_DIR)/docker/docker-compose.yml down

docker-logs: ## Tail logs
	docker compose -f $(BACKEND_DIR)/docker/docker-compose.yml logs -f

# ─── Quality ──────────────────────────────────────────────────────────────────

lint: ## Run linters
	@cd $(BACKEND_DIR) && uv run ruff check .

format: ## Run formatters
	@cd $(BACKEND_DIR) && uv run ruff format .

typecheck: ## Run type checker
	@cd $(BACKEND_DIR) && uv run mypy src/nexus

test: ## Run tests
	@cd $(BACKEND_DIR) && uv run pytest

# ─── Cleanup ──────────────────────────────────────────────────────────────────

clean: ## Clean up temporary files
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .venv -exec rm -rf {} + 2>/dev/null || true
	@rm -rf $(FRONTEND_DIR)/node_modules $(FRONTEND_DIR)/dist
	@echo "Cleaned."
