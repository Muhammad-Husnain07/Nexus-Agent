# Tool Registration Guide

> **⚠️ Security Warning**
> This system supports **HTTP API** and **MCP connections ONLY**.
> Custom Python code execution is **NOT supported** for security reasons.

Every application capability is exposed to the agent as a **tool**. The agent
never calls APIs directly — it selects and invokes tools through the
`ToolRegistry` and `ToolExecutor`. All tools communicate over HTTP to external
services; there is no mechanism for executing arbitrary code on the server.

---

## ToolCreate Schema

```json
{
  "name": "send_email",
  "description": "Send an email via the notification service",
  "purpose": "Send transactional or notification emails to users",
  "endpoint_url": "https://api.example.com/v1/email/send",
  "http_method": "POST",
  "auth_type": "bearer",
  "auth_ref": "env:EMAIL_SERVICE_API_KEY",
  "input_schema": { ... },
  "output_schema": { ... },
  "validation_rules": { ... },
  "examples": [ ... ],
  "tags": ["communication", "transactional"],
  "category": "notifications",
  "requires_approval": false,
  "risk_level": "low",
  "enabled": true
}
```

### Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | **Yes** | Unique per tenant. Lowercase, no spaces. Use `snake_case`. |
| `description` | string | No | Human-readable. **This is what the LLM reads** to decide if this tool matches the user's intent. Be specific. |
| `purpose` | string | No | When to use this tool. Helps the LLM understand context. |
| `endpoint_url` | string | **Yes** | Full URL including protocol. The executor calls this endpoint. |
| `http_method` | string | No | `GET`, `POST`, `PUT`, `DELETE`, `PATCH`. Default: `GET`. |
| `auth_type` | string | No | `none`, `bearer`, `basic`, `api_key`, `oauth2`. Default: `none`. |
| `auth_ref` | string | No | Reference to stored credential (encrypted at rest). Format: `env:VAR_NAME`, `vault:path/to/secret`, or `literal:value`. Never commit actual credentials. |
| `input_schema` | JSON Schema | **Yes** | Declares what parameters the tool expects. The agent uses this to validate arguments before calling. |
| `output_schema` | JSON Schema | No | Declares the response shape. Used for validation (soft-fail on mismatch). |
| `validation_rules` | JSON | No | Business rules beyond schema (e.g. `{"max_length": 1000}`). |
| `examples` | array | No | **Highly recommended.** Few-shot examples help the LLM use the tool correctly. |
| `tags` | array | No | Categorisation for semantic search and filtering. |
| `category` | string | No | Functional group: `notifications`, `data`, `admin`, `utilities`, etc. |
| `requires_approval` | bool | No | If `true`, every invocation requires human approval via HITL. |
| `risk_level` | string | No | `low`, `medium`, `high`. `medium`+ triggers HITL. |
| `enabled` | bool | No | Soft-disable without removing the tool. |

---

## Writing Good Descriptions (LLM Eats These)

The LLM reads the `name`, `description`, and `purpose` fields to decide which tool to call. Follow these principles:

**Good:**
```json
{
  "name": "search_customer_records",
  "description": "Finds customer accounts by email, name, or customer ID. Returns account details including status, plan, and billing info.",
  "purpose": "Use this when the user asks about a customer, needs to look up an account, or wants customer details."
}
```

**Bad:**
```json
{
  "name": "api_v1_customer_search_GET",
  "description": "Endpoint for customer data retrieval",
  "purpose": "Internal"
}
```

**Rules of thumb:**
- Start with the action verb (`Searches`, `Creates`, `Deletes`, `Updates`)
- Include what parameters the LLM should ask the user for
- Mention the output format if relevant
- Avoid implementation details (URLs, auth mechanisms, status codes)
- Keep it 1-3 sentences

---

## Input / Output Schema Examples

### Simple Object

```json
{
  "input_schema": {
    "type": "object",
    "properties": {
      "to": {"type": "string", "format": "email", "description": "Recipient email address"},
      "subject": {"type": "string", "maxLength": 200, "description": "Email subject line"},
      "body": {"type": "string", "description": "Email body content"}
    },
    "required": ["to", "subject"]
  }
}
```

### Nested

```json
{
  "input_schema": {
    "type": "object",
    "properties": {
      "name": {"type": "string", "minLength": 1},
      "items": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "product_id": {"type": "string"},
            "quantity": {"type": "integer", "minimum": 1}
          },
          "required": ["product_id"]
        }
      }
    },
    "required": ["name"]
  }
}
```

### Paginated Output

```json
{
  "output_schema": {
    "type": "object",
    "properties": {
      "results": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "id": {"type": "string"},
            "title": {"type": "string"},
            "score": {"type": "number"}
          }
        }
      },
      "total": {"type": "integer"},
      "page": {"type": "integer"}
    },
    "required": ["results", "total"]
  }
}
```

---

## Authentication Types

| `auth_type` | Description | Header | Example `auth_ref` |
|-------------|-------------|--------|-------------------|
| `none` | No authentication | — | `""` |
| `bearer` | Bearer token (OAuth2, JWT, PAT) | `Authorization: Bearer <token>` | `env:MY_API_TOKEN` |
| `basic` | Base64-encoded user:password | `Authorization: Basic <base64>` | `env:MY_BASIC_CRED` |
| `api_key` | API key in configurable header | `X-API-Key: <key>` | `env:MY_API_KEY` |
| `oauth2` | OAuth2 bearer token | `Authorization: Bearer <token>` | `env:MY_OAUTH_TOKEN` |

For `oauth2`, the executor resolves the token via the configured auth store and
injects it as a Bearer token. The token URL and client credentials are stored
in the credential vault referenced by ``auth_ref``.

Credentials are **encrypted at rest** using AES-256-GCM and are never exposed
in logs or error messages.

### Auth Reference Formats

| Format | Example | Description |
|--------|---------|-------------|
| `env:VAR_NAME` | `env:EMAIL_SERVICE_API_KEY` | Read from environment variable at runtime |
| `vault:path` | `vault:secret/tools/email-key` | Resolve via the configured secret manager |
| `literal:value` | `literal:sk-...` | Inline value (for development only — never commit) |

> **Warning**: Never commit actual credentials in tool definitions. Use
> ``env:VAR_NAME`` or ``vault:path`` in the ``auth_ref`` field and set the
> corresponding secret in your environment or vault.

---

## Connecting to External APIs

Follow this step-by-step guide to connect your API to the agent.

### Step 1: Choose Your Endpoint

Identify the HTTP endpoint the agent will call. It must be reachable from
the Nexus Agent server (not the client browser).

### Step 2: Determine Authentication

Choose one of the supported auth types from the table above. Most APIs use
either `bearer` (OAuth2, JWT) or `api_key`. Store the credential in your
environment or vault:

```bash
export MY_API_TOKEN="sk-abc123..."
```

### Step 3: Design the Input / Output Schemas

Define what the agent should send (input) and what it will receive (output).
See the [Input / Output Schema Examples](#input--output-schema-examples)
section for reference. Schemas must conform to JSON Schema Draft 7.

### Step 4: Register the Tool

Use the **Tool Builder** UI or the API directly:

```bash
curl -X POST https://your-api.com/api/v1/tools \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "search_products",
    "endpoint_url": "https://api.example.com/v1/products/search",
    "http_method": "GET",
    "auth_type": "bearer",
    "auth_ref": "env:PRODUCTS_API_KEY",
    "tool_type": "http_api",
    "input_schema": {
      "type": "object",
      "properties": {
        "q": {"type": "string", "description": "Search keyword"}
      },
      "required": ["q"]
    }
  }'
```

### Step 5: Test the Tool

Use the **Test Playground** or the test endpoint:

```bash
curl -X POST https://your-api.com/api/v1/tools/$TOOL_ID/test?dry_run=false \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"q": "wireless headphones"}'
```

---

## Connecting to MCP Servers

The Model Context Protocol (MCP) is an open standard for connecting AI
applications with external tools and data sources. Nexus Agent supports
connecting to **external MCP servers** as tool providers.

### What is MCP?

MCP defines a JSON-RPC-based protocol over HTTP with two primary methods:

| Method | Purpose |
|--------|---------|
| `tools/list` | Returns available tools with schemas |
| `tools/call` | Invokes a specific tool with arguments |

### Registering an MCP Tool

Set `tool_type` to `"mcp"` and provide the server URL:

```json
{
  "name": "mcp_docs_search",
  "description": "Searches internal documentation via the MCP knowledge server.",
  "tool_type": "mcp",
  "mcp_server_url": "https://mcp.internal.example.com",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {"type": "string", "description": "Search query"},
      "max_results": {"type": "integer", "default": 5}
    },
    "required": ["query"]
  }
}
```

### How Discovery Works

When the agent selects an MCP tool, the executor calls
`MCPClient.list_mcp_tools(server_url)` to discover available tools. The
discovered definitions are cached per server URL.

### MCP vs HTTP API Tools

| Aspect | HTTP API (`http_api`) | MCP (`mcp`) |
|--------|----------------------|-------------|
| Protocol | REST / GraphQL / any HTTP | JSON-RPC 2.0 |
| Discovery | Manual registration | Automatic via `tools/list` |
| Auth | Per-token (bearer, api_key, etc.) | Per-server token passed as header |
| Schema | Defined in `input_schema` | Provided by server response |
| Use case | Any HTTP endpoint | MCP-compatible servers |

### Examples with curl

**Bearer token:**
```bash
curl -X POST https://api.example.com/v1/email/send \
  -H "Authorization: Bearer sk-abc123" \
  -H "Content-Type: application/json" \
  -d '{"to":"user@test.com","subject":"Hello"}'
```

**API key header:**
```bash
curl -X GET https://api.example.com/v1/search?q=deployment \
  -H "X-API-Key: abc123"
```

**Basic auth:**
```bash
curl -X GET https://api.example.com/v1/users \
  -H "Authorization: Basic $(echo -n 'user:pass' | base64)"
```

---

## Tool Examples by Pattern

### REST GET — Search Documents

```json
{
  "name": "search_docs",
  "description": "Searches internal documentation by keyword. Returns matching document titles, URLs, and relevance scores.",
  "endpoint_url": "https://wiki.example.com/api/v1/search",
  "http_method": "GET",
  "auth_type": "bearer",
  "auth_ref": "env:WIKI_API_TOKEN",
  "input_schema": {
    "type": "object",
    "properties": {
      "q": {"type": "string", "description": "Search query"},
      "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}
    },
    "required": ["q"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "results": {"type": "array", "items": {"type": "object"}},
      "total": {"type": "integer"}
    }
  },
  "tags": ["search", "knowledge"],
  "category": "knowledge"
}
```

### REST POST — Send Email

```json
{
  "name": "send_email",
  "description": "Sends an email via the notification service.",
  "endpoint_url": "https://notify.example.com/api/v1/email/send",
  "http_method": "POST",
  "auth_type": "api_key",
  "auth_ref": "env:NOTIFY_API_KEY",
  "input_schema": {
    "type": "object",
    "properties": {
      "to": {"type": "string", "format": "email"},
      "subject": {"type": "string", "maxLength": 200},
      "body": {"type": "string"}
    },
    "required": ["to", "subject"]
  },
  "risk_level": "low",
  "examples": [{
    "user_prompt": "Send an email to john@example.com with subject 'Hello' saying 'Just checking in'",
    "expected_tool": "send_email",
    "sample_input": {"to": "john@example.com", "subject": "Hello", "body": "Just checking in"},
    "sample_output": {"message_id": "msg_abc123", "status": "sent"}
  }]
}
```

### GraphQL — Query Users

```json
{
  "name": "query_users",
  "description": "Queries user accounts via GraphQL. Returns user profiles matching filters.",
  "endpoint_url": "https://api.example.com/graphql",
  "http_method": "POST",
  "auth_type": "bearer",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "GraphQL query string",
        "examples": ["query { users(limit: 10) { id name email role } }"]
      },
      "variables": {"type": "object"}
    },
    "required": ["query"]
  },
  "category": "data"
}
```

### Webhook — Incoming Notification

```json
{
  "name": "process_notification",
  "description": "Processes an incoming webhook notification. Requires HITL approval for destructive actions.",
  "endpoint_url": "https://hooks.example.com/nexus/process",
  "http_method": "POST",
  "auth_type": "none",
  "requires_approval": true,
  "risk_level": "medium",
  "input_schema": {
    "type": "object",
    "properties": {
      "event": {"type": "string", "enum": ["user.created", "order.cancelled", "alert"]},
      "payload": {"type": "object"}
    },
    "required": ["event", "payload"]
  },
  "category": "webhooks"
}
```

---

## Best Practices

### Granular Tools

Prefer many small, focused tools over one large tool:

```json
// ✅ Good — two granular tools
{"name": "search_users", "description": "Searches users by name or email"}
{"name": "create_user", "description": "Creates a new user account"}

// ❌ Bad — one monolithic tool
{"name": "user_management", "description": "Manages users"}
```

### Clear Names

- Use `snake_case` (consistency with Python conventions)
- Start with an action verb: `send_`, `search_`, `create_`, `delete_`, `list_`
- Be specific: `search_customer_records` not `data_lookup`

### The `examples` Field

Examples are the closest thing to few-shot learning for the LLM:

```json
"examples": [
  {
    "user_prompt": "Send an email to john@example.com saying the meeting is at 3pm",
    "expected_tool": "send_email",
    "sample_input": {"to": "john@example.com", "subject": "Meeting reminder", "body": "The meeting is at 3pm"},
    "sample_output": {"message_id": "msg_001", "status": "sent"}
  }
]
```

- Provide 2-3 diverse examples covering different parameter combinations
- Include edge cases (e.g., optional vs required fields)
- The `sample_input` must validate against `input_schema`
- The `sample_output` must validate against `output_schema`

### Risk Levels

| Level | Description | HITL Required |
|-------|-------------|---------------|
| `low` | Read-only, non-destructive | No (unless `requires_approval=true`) |
| `medium` | Modifies data, side effects | **Yes** (by default) |
| `high` | Destructive, data deletion, billing | **Yes** (always) |

---

## Troubleshooting

### CORS Errors

**Symptom**: Browser console shows CORS errors when testing via the UI.

**Causes & solutions**:
1. The backend's `cors_origins` setting doesn't include your frontend origin
   → Update `NEXUS_SERVER__CORS_ORIGINS` in your `.env` file
2. For embed widgets: the domain is not in `allowed_domains`
   → Update the embed config via `PUT /api/v1/embeds/{embed_id}`

### Authentication Failures

**Symptom**: Tool returns 401 Unauthorized or 403 Forbidden.

**Causes & solutions**:
1. `auth_ref` points to a missing environment variable
   → Check that `env:VAR_NAME` is set and accessible
2. The credential has expired or been rotated
   → Update the secret in your vault and verify the `auth_ref`
3. `auth_type` doesn't match what the API expects
   → Verify the API's auth scheme (Bearer vs Basic vs API Key)

### Timeouts

**Symptom**: Tool consistently returns timeout errors.

**Causes & solutions**:
1. The endpoint is too slow for the default 30s timeout
   → Increase `NEXUS_TOOLS__EXECUTION_TIMEOUT_S` in settings
2. Network latency between server and endpoint
   → Check connectivity, firewall rules, DNS resolution
3. The endpoint requires a warm-up period
   → Consider a health-check endpoint or keep-alive mechanism

### Schema Validation Errors

**Symptom**: Tool returns "Input validation failed" or "Output validation failed".

**Causes & solutions**:
1. `input_schema` doesn't match the API's actual parameters
   → Review API documentation and update the schema
2. The agent generated arguments that don't conform to the schema
   → Add more descriptive field descriptions and examples
3. Schema uses Draft 4 or Draft 2020-12 features not supported by
   the validator
   → Ensure schema conforms to **JSON Schema Draft 7**

### Rate Limiting

**Symptom**: Tool returns 429 Too Many Requests or "Rate limit exceeded".

**Causes & solutions**:
1. The tool's `rate_limit_per_minute` is set too low
   → Increase the value via `PUT /api/v1/tools/{tool_id}`
2. Redis token bucket has been exhausted
   → Wait for the refill period (capacity / rate seconds)
3. Multiple concurrent agent runs are consuming tokens
   → Increase the rate limit or reduce agent parallelism

### Connection Refused

**Symptom**: Tool returns "Connection refused" when executing.

**Causes & solutions**:
1. The endpoint URL is incorrect
   → Verify the URL in the tool definition
2. The external service is down
   → Check the service status and restart if needed
3. A firewall or network policy is blocking the connection
   → Check network ACLs, security groups, and DNS resolution
4. The host is not in the sandbox whitelist
   → Add the host to `NEXUS_TOOLS__ALLOWED_HOSTS`
