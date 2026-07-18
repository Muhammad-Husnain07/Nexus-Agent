# Architecture

## Overview

Nexus Agent is a standalone, vendor-neutral agentic AI orchestration layer. It exposes a conversational AI that plans, reasons, gathers requirements, and invokes application capabilities via registered tools. The AI contains **zero business logic** — it is a pure orchestration brain that delegates all domain work to tools.

---

## System Context

```mermaid
graph TB
    User[User / Chat UI] -->|SSE / WebSocket| FastAPI[FastAPI Server]
    FastAPI -->|Streams events| User
    FastAPI --> Agent[LangGraph Agent]
    Agent --> LLM[LLM Provider]
    Agent --> ToolExec[ToolExecutor]
    FastAPI --> Auth[Auth Middleware]
    FastAPI --> Tenant[Tenant Middleware]
    ToolExec -->|HTTP| ExternalAPI[External APIs]
    Agent --> Memory[Memory / Checkpointer]
    Memory --> PG[(PostgreSQL + pgvector)]
    FastAPI --> Redis[(Redis 7)]
    FastAPI --> MCP[MCP Server]
    MCP -->|MCP Protocol| MCPClient[Claude Desktop / Cline]
```

---

## Component Responsibilities

| Component | Module | Responsibility |
|-----------|--------|---------------|
| **FastAPI Server** | `src/nexus/api/` | HTTP routes, middleware, SSE streaming, websockets |
| **LangGraph Agent** | `src/nexus/agent/` | ReAct + Plan-and-Execute reasoning loop |
| **LLM Client** | `src/nexus/llm/` | Unified interface to 100+ LLM providers (LiteLLM) |
| **Tool Registry** | `src/nexus/tools/` | CRUD, discovery, semantic search, MCP exposure |
| **Tool Executor** | `src/nexus/tools/executor.py` | Executes HTTP API calls and MCP server requests with retry logic — no code execution |
| **Memory** | `src/nexus/memory/` | Short-term checkpointer + long-term pgvector store |
| **Sessions** | `src/nexus/sessions/` | Conversation history, context window management |
| **HITL** | `src/nexus/agent/hitl.py` | Human-in-the-loop approval interrupts |
| **Auth** | `src/nexus/security/` | JWT, API keys, RBAC, credential vault |
| **Multi-Tenant** | `src/nexus/db/context.py` | contextvar-based tenant isolation |
| **Embed API** | `src/nexus/api/embed.py` | Embed widget CRUD, token generation, usage analytics |
| **Embed Middleware** | `src/nexus/middleware/embed_auth.py` | Embed token validation, domain whitelist, per-token rate limiting |
| **Observability** | `src/nexus/observability/` | OpenTelemetry, structlog, Prometheus metrics |
| **Error Handling & Resilience** | `src/nexus/errors/` | Circuit breakers, retry policies, dead letter queue, graceful degradation |
| **Configuration** | `src/nexus/config/` | Pydantic BaseSettings, secret management |
| **Utilities** | `src/nexus/utils/` | Scheduled jobs, constants |
| **Python SDK** | `src/nexus_sdk/` | Client library for external integrations |

---

## Data Flow — Chat Turn

```mermaid
sequenceDiagram
    participant Client
    participant FastAPI
    participant Router
    participant Agent
    participant LLM
    participant Tools
    participant DB

    Client->>FastAPI: POST /api/v1/sessions/{id}/chat {message, stream:true}
    FastAPI->>Router: Authenticate + resolve tenant
    Router->>Agent: AgentRunner.invoke()
    Agent->>LLM: understand_intent
    LLM-->>Agent: IntentAnalysis
    Agent->>FastAPI: SSE: tool_selected
    FastAPI-->>Client: event: tool_selected
    Agent->>Tools: DynamicToolSelector.select()
    Tools-->>Agent: [ToolRead]
    Agent->>LLM: plan(goal, tools)
    LLM-->>Agent: Plan(steps)
    Agent->>FastAPI: SSE: plan_created
    FastAPI-->>Client: event: plan_created
    Agent->>Tools: ToolExecutor.execute(tool, inputs)
    Tools->>DB: INSERT ToolExecution
    Tools-->>Agent: ToolResult
    Agent->>FastAPI: SSE: tool_call_completed
    FastAPI-->>Client: event: tool_call_completed
    Agent->>LLM: analyze_results
    LLM-->>Agent: AnalysisResult(finalize)
    Agent->>FastAPI: SSE: final_response
    FastAPI-->>Client: event: final_response
    FastAPI-->>Client: event: done
```

---

## Data Flow — HITL Approval

```mermaid
sequenceDiagram
    participant Client
    participant Agent
    participant HITL
    participant Tools
    participant DB

    Agent->>HITL: requires_approval(tool, step)
    HITL-->>Agent: True
    Agent->>HITL: interrupt_for_approval(payload)
    HITL->>FastAPI: SSE: approval_required
    FastAPI-->>Client: event: approval_required (stream closes)
    
    Client->>FastAPI: POST /api/v1/approvals/{id}/decide {action:"approve"}
    FastAPI->>DB: INSERT Approval(status=approved)
    FastAPI->>Agent: graph.astream(Command(resume={action:"approve"}))
    Agent->>Tools: ToolExecutor.execute()
    Tools-->>Agent: ToolResult
    Agent->>FastAPI: SSE: final_response
    FastAPI-->>Client: event: final_response
```

---

## Data Flow — API-Only Tool Execution

```mermaid
sequenceDiagram
    participant LLM[LLM Provider]
    participant Agent[LangGraph Agent]
    participant Executor[ToolExecutor]
    participant MCP[MCPClient]
    participant HTTP[httpx Client]
    participant API[External API / MCP Server]

    Agent->>LLM: decide_tool(intent)
    LLM-->>Agent: select tool + generate inputs
    Agent->>Executor: execute(tool, inputs)

    alt tool_type == "http_api"
        Executor->>HTTP: outbound HTTP call
        HTTP->>API: GET/POST/PUT/DELETE
        API-->>HTTP: Response
        HTTP-->>Executor: ToolResult
    else tool_type == "mcp"
        Executor->>MCP: call_mcp_tool()
        MCP->>API: JSON-RPC tools/call
        API-->>MCP: ToolResult
        MCP-->>Executor: ToolResult
    end

    Executor->>Executor: Validate output schema
    Executor->>Executor: Persist ToolExecution row
    Executor-->>Agent: ToolResult
```

The executor never executes code. It either makes an HTTP call via httpx
(``http_api``) or sends a JSON-RPC request via MCPClient (``mcp``).
All authentication, sandbox host whitelisting, and rate limiting is applied
before the request leaves the executor.

---

## Data Flow — Tool Registration

```mermaid
sequenceDiagram
    participant Developer
    participant API
    participant Registry
    participant Secrets[SecretResolver]
    participant LLM
    participant DB

    Developer->>API: POST /api/v1/tools {name, description, auth, schemas}
    API->>API: Validate auth & RBAC (tools:register)
    API->>API: Validate no Python code fields
    API->>API: Validate JSON Schema Draft 7
    API->>Registry: registry.register(session, tenant_id, tool)
    Registry->>Secrets: Encrypt auth_ref (AES-256-GCM)
    Secrets-->>Registry: ciphertext
    Registry->>LLM: embed(name + description + purpose + tags)
    LLM-->>Registry: list[float] (1536-dim vector)
    Registry->>DB: INSERT Tool + encrypted auth_ref + embedding
    DB-->>Registry: Tool(id, version=1)
    Registry-->>API: ToolRead (auth_ref reference, not value)
    API-->>Developer: 201 Created + ToolRead JSON
```

---

## Data Flow — Multi-Tenant Request

```mermaid
sequenceDiagram
    participant Client
    participant TenantMW
    participant App
    participant DB

    Client->>TenantMW: POST /api/v1/tools (X-Tenant-ID: uuid)
    TenantMW->>TenantMW: set_tenant(tenant_id) via contextvar
    TenantMW->>DB: SELECT Tenant WHERE id = ...
    DB-->>TenantMW: Tenant(status=active)
    TenantMW->>App: call_next(request)
    App->>DB: all queries filtered by get_tenant()
    DB-->>App: tenant-scoped results
    App-->>Client: Response with X-Tenant-ID header
```

---

## Deployment Architecture

```mermaid
graph TB
    subgraph Docker Compose
        App[Nexus Agent :8000]
        PG[(PostgreSQL+pgvector :5432)]
        RD[(Redis 7 :6379)]
    end
    subgraph Optional
        LLMP[LiteLLM Proxy :4000]
        OTEL[OpenTelemetry Collector :4318]
        PM[Prometheus :9090]
    end
    Client-->App
    App-->PG
    App-->RD
    App-->LLMP
    LLMP-->LLM[LLM APIs]
    App-->OTEL
    PM-->App
    App-->|/metrics|PM
```

---

## Security Model

```mermaid
graph LR
    Request[HTTP Request] --> Auth{Authentication}
    Auth -->|Bearer JWT| JWTVerify[JWT Verification]
    Auth -->|API Key| KeyVerify[Argon2 Hash Comparison]
    
    JWTVerify --> RBAC{RBAC}
    KeyVerify --> RBAC
    
    RBAC -->|tenant_admin| Admin[Full Access]
    RBAC -->|developer| Dev[Tools + Sessions]
    RBAC -->|end_user| User[Chat + Read Tools]
    RBAC -->|viewer| Viewer[Read Only]
    
    ToolExec[ToolExecutor] --> Authz{Authz Gate}
    Authz -->|requires_approval| HITL[Human Approval]
    Authz -->|risk_level=high| HITL
    Authz -->|safe| HTTP[HTTP Call / MCP Request]
```

### Why No Python Code Execution

Nexus Agent deliberately **does not support** executing arbitrary Python
(or any other language) code as part of tool definitions. This is a
security-by-design decision with the following rationale:

| Risk | Description | Mitigation in Nexus |
|------|-------------|-------------------|
| **Sandbox escape** | Even sandboxed code execution environments have known escape vectors that could expose the host system | No code execution means no sandbox needed |
| **Supply chain attacks** | Code-based tools could pull in malicious dependencies | All tool logic runs externally — no packages installed server-side |
| **Resource exhaustion** | Unbounded code could consume CPU, memory, or disk | HTTP timeout (configurable) enforces resource limits at the network level |
| **Data exfiltration** | Malicious code could read or transmit sensitive data | Tools only receive the data sent as HTTP arguments and only return HTTP responses |
| **Auditability** | Code execution makes it hard to audit what a tool actually did | Every tool call produces a persisted `ToolExecution` row with inputs, outputs, and timing |

If you need custom logic, the recommended approach is to **deploy it as a
separate microservice** and register it as an HTTP API tool. The microservice
handles the custom logic, and Nexus Agent simply calls its HTTP endpoint.
This keeps the agent's attack surface minimal and allows each service to have
its own security controls.

### Credential Encryption

All tool authentication credentials stored in the database are **encrypted at
rest** using AES-256-GCM. The encryption key is derived from the application
secret and is never logged or exposed via the API. On tool execution, the
`SecretResolver` decrypts the credential in memory, injects it into the HTTP
request headers, and discards it after the request completes.

The `auth_ref` field in the tool definition stores a reference (not the
credential itself) using one of these formats:

| Format | Example | Security Level |
|--------|---------|---------------|
| `env:VAR_NAME` | `env:EMAIL_SERVICE_API_KEY` | Medium — env var on server |
| `vault:path` | `vault:secret/tools/email-key` | High — external secret manager |
| `literal:value` | `literal:sk-...` | Low — visible in API responses (dev only) |

---

## Conversational Loop

The agent is **multi-turn** by design. When it needs clarification, the `gather_requirements` node asks questions and the graph routes to `END`. The user responds with a new message, which re-enters the graph at `understand_intent`. This cycle repeats until all required information is gathered:

```
User message → understand_intent
  ├─ Enough info? → discover_tools → plan → execute_step → ...
  └─ Missing info? → gather_requirements → ask questions → END
                                                    ↓
                              User replies → understand_intent (merges answers) → ...
```

This avoids internal clarification loops and gives the user a natural back-and-forth experience. Each turn is a complete conversation round-trip.

## Architecture Decision Records

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Agent framework | LangGraph 1.0 | Purpose-built for stateful agents with interrupts, checkpointing |
| LLM abstraction | LiteLLM | 100+ providers, unified API, cost tracking |
| Multi-tenancy | contextvar + tenant_id per row | Zero-copy isolation, no connection overhead |
| HITL mechanism | LangGraph interrupt() | First-class resume support, checkpointing |
| Streaming | SSE (preferred) + WebSocket | Browser-native EventSource, bidirectional fallback |
| Tool protocol | MCP + REST | Industry standard for tool discovery, dual interface |
| Embedding similarity | pgvector (<=> cosine) | In-database search, no external vector store |
| Async runtime | asyncio + FastAPI | Non-blocking I/O, SSE/WebSocket support |
