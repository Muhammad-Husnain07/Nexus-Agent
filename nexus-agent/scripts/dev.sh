#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

uv run alembic upgrade head
exec uv run uvicorn nexus.main:app --reload --host 0.0.0.0 --port 8000
