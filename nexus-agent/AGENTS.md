# Nexus Agent — AGENTS.md

## Mission

**Nexus Agent** is a standalone, vendor-neutral agentic AI orchestration layer. It exposes a conversational AI that plans, reasons, gathers requirements, and invokes application capabilities via registered tools. The AI contains **zero business logic** — it is a pure orchestration brain that delegates all domain work to tools.

---

## Locked Tech Stack

| Layer | Choice | Exact Version | License |
|-------|--------|---------------|---------|
| Language | Python | 3.12+ | PSF |
| Agent orchestration | LangGraph | 1.0 (stable) | MIT |
| Type safety | Pydantic | v2 | MIT |
| Tool schemas | Pydantic AI | — | MIT |
| Web framework | FastAPI | >=0.135.0 (async, SSE) | MIT |
| LLM abstraction | LiteLLM | latest (unified OpenAI-compatible) | MIT |
| Database | PostgreSQL 16 + pgvector | 16 | PostgreSQL |
| ORM | SQLAlchemy 2.0 async + asyncpg | 2.0 | MIT |
| Migrations | Alembic | — | MIT |
| Cache/queue | Redis | 7 | BSD-3 |
| Tool protocol | Model Context Protocol (MCP) | — | MIT |
| Tool registry | Custom (hybrid with MCP) | — | MIT |
| Tracing | LangSmith | — | —
| Observability | OpenTelemetry + structlog | — | MIT/Apache 2.0 |
| Testing | pytest + pytest-asyncio + respx + factory-boy | — | MIT |
| Evals | LangSmith evals | — | —
| Lint | ruff | — | MIT |
| Format | ruff-format | — | MIT |
| Type check | mypy (strict) | — | MIT |
| Pre-commit | pre-commit hooks | — | MIT |
| Package manager | uv | — | Apache 2.0 |
| Containerization | Docker + docker-compose + K8s manifests | — | —

---

## Architecture Principles

1. **Tool-driven** — All business capability is behind tool boundaries. The agent never calls a database or external API directly.
2. **Vendor-neutral** — LLM providers, vector stores, and infrastructure are swappable via config/env vars.
3. **Multi-tenant** — Every database row carries `tenant_id`. Isolation at the query layer.
4. **HITL-first (Human-in-the-Loop)** — Every tool invocation can require human approval. The agent never executes destructive actions autonomously unless explicitly configured.
5. **Stateless agent, stateful session** — The agent is ephemeral; conversation state, memory, and tool results live in PostgreSQL/Redis.
6. **Fail closed** — On error, ambiguity, or policy violation, the agent defers to the human.

---

## Coding Standards

- **Async-first** — All I/O uses `asyncio`. No blocking calls in the hot path.
- **Type-hinted everywhere** — Every function/method has full type annotations. Use `TYPE_CHECKING` for circular imports.
- **Pydantic for all schemas** — Every input, output, config, and data transfer object is a Pydantic v2 `BaseModel`.
- **Dependency injection** — Use FastAPI `Depends` and `Annotated` patterns. No `request` globals.
- **No global mutable state** — Zero module-level mutable variables. Use `functools.lru_cache` or `@singledispatch` where needed.
- **Structured logging** — `structlog` for all logging. No `print()`, no `logging.debug(...)` strings.
- **Error handling** — Custom exception hierarchy in `src/nexus/errors/`. All unexpected errors captured by middleware.
- **Idempotency** — Tool invocations should be idempotent where possible.
- **Configuration** — All configuration via Pydantic `BaseSettings` in `src/nexus/config/`.

---

## File-Scoped Commands

```bash
# Lint
uv run ruff check .

# Format
uv run ruff format .

# Type check
uv run mypy src/nexus

# Run tests
uv run pytest

# Run DB migrations
uv run alembic upgrade head

# Generate migration
uv run alembic revision --autogenerate -m "description"
```

---

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Modules | `snake_case` | `tool_registry.py` |
| Functions/Methods | `snake_case` | `get_tenant_session()` |
| Classes/Models | `PascalCase` | `AgentState`, `ToolInvocation` |
| Env vars | `UPPER_CASE` | `DATABASE_URL`, `REDIS_URL` |
| Constants | `UPPER_CASE` | `MAX_RETRY_COUNT` |
| Private members | `_leading_underscore` | `_validate_tool()` |
| Tests | `test_<module>_<scenario>` | `test_tool_registry_discover.py` |

---

## Rules

1. **Every public function has a docstring** — Google-style with `Args:`, `Returns:`, `Raises:`.
2. **Every Pydantic model has field descriptions** — `field(description="...")` on every field.
3. **Never call LLMs or tools directly outside their dedicated modules** — LLM calls only in `src/nexus/llm/`, tool invocation only in `src/nexus/tools/`.
4. **No business logic in prompts** — Prompts describe the agent's role, tool schema, and guardrails — never domain rules.
5. **Every tool must declare idempotency, cost, and safety level** — via metadata on the tool schema.
6. **All secrets via environment variables** — never hardcoded, never committed.
7. **All migrations must be reversible** — Alembic `downgrade()` always present.

---

## Architecture Reference

See [docs/architecture.md](docs/architecture.md) for detailed architecture documentation and decision records.

---

## Nested AGENTS.md Placeholders

### `src/nexus/agent/AGENTS.md`

This module owns the LangGraph orchestration graph. Key responsibilities:
- Define `StateGraph` topologies for conversational + autonomous flows.
- Manage graph lifecycle (compile, checkpoint, stream).
- Provide `AgentExecutor` class that wires LLM, tools, memory, and human-in-the-loop.
- Implement supervisor + sub-agent patterns via `StateGroup` / `subgraphs`.

### `src/nexus/tools/AGENTS.md`

This module owns tool registration, discovery, and invocation. Key responsibilities:
- `ToolRegistry` — Pydantic-backed registry of all known tools.
- MCP client for discovering external MCP servers (discover, fetch schema).
- Tool execution with timeout, retry, idempotency key, and audit logging.
- Tool schema generation from Pydantic models (via Pydantic AI or manual JSON Schema).
- HITL gate (require human approval before execution).

### `src/nexus/api/AGENTS.md`

This module owns the FastAPI application. Key responsibilities:
- Route definitions: `/chat/stream`, `/chat/sync`, `/tools`, `/sessions`, `/health`.
- SSE and WebSocket endpoints for streaming agent responses.
- Middleware: tenant extraction, authn/authz, rate limiting, request ID, structured logging.
- OpenAPI schema generation with all Pydantic models.
- Webhook ingestion for tool callbacks.

### `src/nexus/memory/AGENTS.md`

This module owns the two-tier memory system. Key responsibilities:
- `AsyncPostgresSaver` checkpointer for LangGraph session state persistence.
- `MemoryStore` with pgvector for long-term cross-session memory (episodic, semantic, procedural).
- `EpisodicSummarizer` that condenses conversation history via LLM.
- Memory retrieval and importance scoring for relevant context injection.

### `src/nexus/sessions/AGENTS.md`

This module owns conversation session management. Key responsibilities:
- Session CRUD — create, rename, fork, archive.
- `ContextWindowManager` to track token usage and trigger summarization.
- `SystemPromptBuilder` that assembles dynamic system prompts with memory context.
- Message persistence with branching support (`parent_message_id`).

### `src/nexus/llm/AGENTS.md`

This module owns the LLM integration layer. Key responsibilities:
- `LLMClient` — unified interface to 100+ providers via LiteLLM.
- `ProviderRegistry` — loads provider configs from settings, resolves API keys.
- `ModelRouter` — routes task types (chat, embedding) to the appropriate model.
- `CostTracker` — tracks per-request token usage and cost.
- Fallback chains and retry policies for provider resilience.

### `src/nexus/security/AGENTS.md`

This module owns authentication and authorization. Key responsibilities:
- JWT issuance, refresh, and revocation via `python-jose`.
- API key generation with argon2id hashing and SHA-256 lookup.
- RBAC with role-to-permission mapping (tenant_admin, developer, end_user, viewer).
- Credential encryption for tool auth secrets using AES-GCM.
- Input guard, rate limiting, quota enforcement, and cost alerts.

### `src/nexus/middleware/AGENTS.md`

This module owns the ASGI middleware stack. Key responsibilities:
- `AuthMiddleware` — JWT and API key authentication, sets `request.state.*`.
- `TenantMiddleware` — extracts tenant ID from auth or header, enforces isolation.
- `TieredRateLimitMiddleware` — per-tenant sliding window rate limiter.
- `DrainMiddleware` — graceful shutdown, rejects new requests during drain.
