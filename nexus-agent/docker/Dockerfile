# =============================================================================
# Nexus Agent — Multi-stage Dockerfile
#
# Builder:   installs dependencies via uv
# Runtime:   minimal python:3.12-slim with .venv copied from builder,
#            runs as non-root nexus user, healthcheck, starts uvicorn
# Note:      Migrations are run separately (Job in K8s, dev.sh locally).
#            The app starts without them; /readyz will show degraded until
#            tables exist.
#
# Build args:
#   NEXUS_FRONTEND__API_URL: Backend URL exposed to the frontend
# =============================================================================

ARG NEXUS_FRONTEND__API_URL="http://localhost:8000"

# ── Builder ──────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# ── Runtime ──────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    NEXUS_FRONTEND__API_URL=${NEXUS_FRONTEND__API_URL}

# Install curl for healthcheck, nothing else
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN groupadd -r nexus && useradd -r -g nexus -d /app -s /sbin/nologin nexus

WORKDIR /app

# Copy pre-built venv from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY src/ /app/src/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/

EXPOSE 8000

# Health check — uses /healthz (liveness) and /readyz (readiness)
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

USER nexus

CMD ["uvicorn", "nexus.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
