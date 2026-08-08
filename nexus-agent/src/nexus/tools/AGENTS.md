# `src/nexus/tools/` — Tool Registration, Discovery & Invocation

> **Runtime Contract** (binding): see [`docs/runtime-contract.md`](../../../docs/runtime-contract.md).
> Highlights: executor retry budgets are metadata-driven (`idempotent` → may
> retry; non-idempotent → single attempt via `_effective_max_attempts`); output
> validation follows the tool's `output_schema` (top-level arrays unwrapped);
> registry sync is commit-then-refresh with the persisted cache marker; no
> tool-name-based logic anywhere.

This module owns the tool lifecycle — the only boundary through which the agent touches external applications. Every tool maps to an API endpoint with rich metadata.

## Key Responsibilities

- `ToolRegistry` — Pydantic-backed CRUD registry with automatic embedding generation and pgvector semantic search.
- MCP server via `fastapi-mcp` — exposes tool registry as MCP `tools/list` and `tools/call` for external MCP clients.
- `ToolExecutor` — resilient async HTTP execution with auth injection, schema validation, retry, sandbox, and audit logging.
- `approval_gate` — dynamic HITL approval checks driven entirely by tool metadata (`risk_level` / `requires_approval`). No hardcoded tool names.
- Tool schema generation from Pydantic models via `schemas.py`.

## Key Files

| File | Responsibility |
|------|---------------|
| `registry.py` | `ToolRegistry` — `register()`, `update()` (with version snapshot via `session.run_sync`), `deregister()` (soft-delete), `get()`, `list()` (paginated, filterable), `search_semantic()` (pgvector cosine similarity). Auto-generates embeddings on create/update |
| `executor.py` | `ToolExecutor.execute()` — full pipeline: input validation (JSON Schema) → sandbox host check → auth header resolution → HTTP call with tenacity retry (5xx/408/429) → output validation (soft-fail, with type guard for non-dict data) → persist `ToolExecution` row → publish Redis event |
| `mcp_server.py` | `setup_mcp()` — attaches `FastApiMCP` to the FastAPI app, exposes registry as MCP tools at `/mcp` |
| `schemas.py` | Pydantic models: `ToolCreate`, `ToolUpdate`, `ToolRead` (includes `requires_approval`, `risk_level`), `ToolSearchResult`, `ToolExample`, `ToolVersionDiff` |
| `api.py` | FastAPI router `/tools` — POST (register), GET (list + search), GET/PUT/DELETE by id, POST `/{id}/test` (dry-run or live HTTP call with URL template resolution) |
| `approval_gate.py` | Dynamic approval check — `requires_approval()`, `check_plan_approval()`, `format_approval_message()` (shows tool inputs for per-call scope). Driven by `risk_level` and `requires_approval` metadata |
| `result.py` | `ToolResult` dataclass with status, data, error, duration_ms, raw_response_excerpt |
| `retries.py` | `http_retry_policy` — tenacity retry for tool HTTP calls; `is_retryable_status()`, `parse_retry_after()` |
| `sandbox.py` | `SandboxConfig`, `check_allowed_host()`, `mask_sensitive_fields()` — optional outbound call restrictions |
| `error_recovery.py` | `SemanticErrorClassifier` — pattern-based error classification, field rename suggestions from settings |

## Data Flow (Tool Execution)

```
Agent node → ToolExecutor.execute()
  ├─ jsonschema.validate(inputs, input_schema)
  ├─ check_allowed_host(endpoint_url) — whitelist always; SSRF hardening
  │     (scheme + private/loopback/link-local/DNS-rebinding blocking) for the
  │     DYNAMIC-endpoint class (host influenced by tool inputs)
  ├─ AUTHORIZATION GATE (P0) — validation_rules.allowed_roles must intersect
  │     the caller's roles (context.user_roles); unconfigured = open
  ├─ IDEMPOTENCY (P0) — when validation_rules.idempotency_header is declared,
  │     the invocation's stable idempotency_key is stamped on the request
  │     (the SAME key across retries/recovery — provider-side dedup)
  ├─ resolve_auth(auth_ref) → injects Bearer/Basic/API-Key header
  │     (auth_type/auth_ref resolved from GlobalContext.capability_providers if not in state)
  ├─ HTTP call via httpx with tenacity retry
  ├─ jsonschema.validate(response, output_schema) — soft-fail, type guard for non-dict
  ├─ persist ToolExecution row (status, payloads, duration)
  └─ publish tool_events:{session_id} via Redis pub/sub
```

The executor's gates are metadata-driven: authorization and idempotency ride
the tool's `validation_rules` (the operator-configured contract carrier);
SSRF hardening applies to the dynamic-endpoint class (the resolved host differs
from the registered host). Mid-call cancellation produces the typed
`uncertain` outcome — never retried, never reported as a plain failure.

Approval gating happens at the graph level (`ApprovalGateNode`), not at the executor level. The executor receives `skip_approval=True` because only already-cleared tools reach it.

The executor uses httpx (`trust_env=False` for WSL2 compatibility) for HTTP calls. Auth headers are resolved from settings (`ToolSettings.auth_header_mappings`) and tool metadata, with a fallback to `GlobalContext.capability_providers` when state-level tool data is unavailable.

- `nexus/db/` — Tool, ToolVersion, ToolExecution models; repositories
- `nexus/llm/` — LLMClient.embed for embedding generation
- `nexus/redis_client/` — EventBus for tool events, RedisCache for discovery
- `nexus/config/` — settings for timeouts, retries, sandbox
- `nexus/security/` — SecretResolver for auth refs
