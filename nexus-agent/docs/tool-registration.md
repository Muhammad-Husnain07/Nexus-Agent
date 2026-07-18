# Tool Registration Guide

Every application capability is exposed to the agent as a **tool**. The agent never calls APIs directly — it selects and invokes tools through the `ToolRegistry` and `ToolExecutor`.

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
| `auth_type` | string | No | `none`, `bearer`, `basic`, `api_key`, `oauth2`, `custom`. Default: `none`. |
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
| `bearer` | Bearer token in Authorization header | `Authorization: Bearer <token>` | `env:MY_API_TOKEN` |
| `basic` | Base64-encoded user:password | `Authorization: Basic <base64>` | `env:MY_BASIC_CRED` |
| `api_key` | Custom header for API key | `X-API-Key: <key>` | `env:MY_API_KEY` |
| `oauth2` | OAuth2 bearer token | `Authorization: Bearer <token>` | `env:MY_OAUTH_TOKEN` |
| `custom` | Custom auth logic | Configurable by subclasses | Varies |

For `oauth2`, the executor resolves the token via the configured auth store and
injects it as a Bearer token. The token URL and client credentials are stored
in the credential vault referenced by ``auth_ref``.

For `custom`, subclass ``ToolExecutor`` and override ``_resolve_auth()`` to
implement provider-specific logic (e.g., mTLS, custom signing, AWS SigV4).

### Auth Reference Formats

| Format | Example | Description |
|--------|---------|-------------|
| `env:VAR_NAME` | `env:EMAIL_SERVICE_API_KEY` | Read from environment variable at runtime |
| `vault:path` | `vault:secret/tools/email-key` | Resolve via the configured secret manager |
| `literal:value` | `literal:sk-...` | Inline value (for development only — never commit) |

> **Warning**: Never commit actual credentials in tool definitions. Use
> ``env:VAR_NAME`` or ``vault:path`` in the ``auth_ref`` field and set the
> corresponding secret in your environment or vault.

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
