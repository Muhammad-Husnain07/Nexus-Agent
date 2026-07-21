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
3. **Single-tenant** — No tenant isolation; all data is shared. Simplified deployment for single-user/single-team use cases.
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
| Functions/Methods | `snake_case` | `get_session()` |
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

## Module Responsibilities

### `src/nexus/agent/` — LangGraph Orchestration

This module owns the LangGraph StateGraph that implements a DAG-based Plan-and-Execute + Reflection reasoning loop. Key responsibilities:
- Define `StateGraph` topology with 6 parent nodes + 3-node tool subgraph.
- Manage graph lifecycle (compile, checkpoint, stream).
- Provide `AgentRunner` class that wires LLM, tools, memory, event bus, and session lock.
- Human-in-the-Loop via `review_final_answer` / `review_plan` nodes and LangGraph `interrupt()`.
- DAG-based parallel tool execution inside the tool subgraph via `Send()` API.
- Self-reflection via `reflect_on_response` — scores responses and routes to clarification or regeneration.

### `src/nexus/tools/` — Tool Registration, Discovery & Invocation

This module owns the tool lifecycle. Key responsibilities:
- `ToolRegistry` — Pydantic-backed registry of all known tools with automatic embedding generation.
- MCP server via `fastapi-mcp` — exposes tool registry as MCP `tools/list` and `tools/call`.
- `ToolExecutor` — resilient async HTTP execution with auth injection, schema validation, and retry.
- `DynamicToolSelector` — semantic + LLM-reranked discovery with Redis caching.
- HITL gate — approval checking before destructive/risky tool execution.

### `src/nexus/api/` — FastAPI Application & Public API Layer

This module owns the FastAPI application. Key responsibilities:
- Route definitions: `/tools`, `/sessions`, `/chat`, `/approvals`, `/memory`, `/ws`.
- SSE and WebSocket endpoints for streaming agent responses with heartbeat keep-alive.
- Middleware: CORS, rate limiting, request ID, structured logging, error handling, drain.

### `src/nexus/memory/` — Long-Term Memory System

This module owns the two-tier memory system. Key responsibilities:
- `AsyncPostgresSaver` checkpointer for LangGraph session state persistence.
- `MemoryStore` with pgvector for long-term cross-session memory (episodic, semantic, procedural).
- `EpisodicSummarizer` that condenses conversation history via LLM.
- Memory retrieval and importance scoring for relevant context injection.

### `src/nexus/sessions/` — Conversation Session Management

This module owns conversation session management. Key responsibilities:
- Session CRUD — create, rename, fork, archive.
- `ContextWindowManager` to track token usage and manage summarization.
- `SystemPromptBuilder` that assembles dynamic system prompts with memory context.
- Message persistence with branching support (`parent_message_id`).

### `src/nexus/llm/` — LLM Integration

This module owns the LLM integration layer. Key responsibilities:
- `LLMClient` — unified interface to 100+ providers via LiteLLM.
- `ProviderRegistry` — loads provider configs from settings, resolves API keys.
- `ModelRouter` — routes task types (chat, embedding) to the appropriate model.
- Fallback chains and retry policies for provider resilience.

### `src/nexus/security/` — Rate Limiting & Auth

This module owns rate limiting and passthrough auth. Key responsibilities:
- Tiered rate limiting per endpoint prefix via Redis sliding window.
- Passthrough auth middleware (no JWT, no RBAC) — injects default identity.

### `src/nexus/middleware/` — ASGI Middleware Stack

This module owns the ASGI middleware stack. Key responsibilities:
- `AuthMiddleware` — passthrough (no identity injection).
- `TieredRateLimitMiddleware` — per-IP sliding window rate limiter.
- `DrainMiddleware` — graceful shutdown, rejects new requests during drain.
