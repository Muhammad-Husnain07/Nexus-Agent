# Embedding Nexus into your application

Nexus is an embeddable Agent Orchestration Runtime. Developers expose their
application's capabilities through natural language by:

1. **Registering capabilities** (APIs, databases, MCP servers, custom actions)
2. **Defining deterministic workflows** for business processes
3. **Embedding the assistant** — anywhere, with a zero-config widget or the API

This guide covers the embeddable surface. No tool, capability, workflow, or
scenario is hardcoded — everything is registered at runtime via the API and
matched dynamically.

---

## 1. The embeddable widget (any website)

The widget is a single UMD file (`frontend/dist-embed/embed-widget.js`,
built with `npm run build:embed`). Drop it into **any** page — no framework,
no build step:

```html
<!-- inline widget -->
<div data-nexus-chat
     data-api-base="https://assistant.example.com/api/v1"
     data-title="Support Assistant"
     data-greeting="Hi! How can I help today?"
     data-placeholder="Ask about orders, invoices…"
     data-primary="#0f766e"
     data-height="520"
     data-width="380"></div>
<script src="https://assistant.example.com/embed-widget.js"></script>
```

### Floating launcher (chat bubble)

```html
<div data-nexus-chat
     data-api-base="https://assistant.example.com/api/v1"
     data-launcher="true"
     data-position="bottom-right"
     data-title="Assistant"></div>
<script src="https://assistant.example.com/embed-widget.js"></script>
```

### Programmatic mount

```html
<div id="assistant-root"></div>
<script src="https://assistant.example.com/embed-widget.js"></script>
<script>
  window.NexusEmbed.mount(document.getElementById("assistant-root"), {
    apiBase: "https://assistant.example.com/api/v1",
    title: "Support Assistant",
    height: 520,
    width: 380,
    onEvent: (type, payload) => console.log(type, payload),
  });
</script>
```

### Widget options

| Option | data attribute | Default | Purpose |
|--------|----------------|---------|---------|
| `apiBase` | `data-api-base` | `/api/v1` | Nexus API base URL (trailing `/` stripped) |
| `title` | `data-title` | `Assistant` | Header title |
| `placeholder` | `data-placeholder` | `Type a message…` | Input placeholder |
| `greeting` | `data-greeting` | generic | Empty-state message |
| `primary` | `data-primary` | theme | Primary brand color (CSS color) |
| `height` / `width` | `data-height` / `data-width` | `520` / `380` | Panel size in px |
| `launcher` | `data-launcher` | `false` | Floating bubble mode |
| `position` | `data-position` | `bottom-right` | `bottom-right` \| `bottom-left` \| `top-right` \| `top-left` |
| `sessionId` | `data-session-id` | — | Reuse an existing session |
| `persistSession` | `data-persist-session` | `true` | Keep session across reloads (localStorage) |
| `storageKey` | `data-storage-key` | `nexus-widget-session` | localStorage key |
| `zIndex` | `data-z-index` | `2147483000` | Stacking context |
| `onEvent` | — | — | Callback for `final_response`, `approval_checkpoint`, `error`, `done` |

### Widget behaviour

- Conversations persist across reloads (localStorage) when `persistSession`.
- Streaming responses with tool-progress chips.
- **Conversational approval checkpoints are handled inline** — Approve /
  Cancel / Modify buttons appear in-chat for high-risk operations.
- `onEvent` lets the host application react (e.g. track a `final_response`).

---

## 2. Defining deterministic workflows

Workflows are the deterministic counterpart to dynamic planning. Register
them at runtime via the API — no code changes:

```
POST /api/v1/workflows
```

```json
{
  "name": "invoice_approval",
  "description": "Two-step invoice approval",
  "trigger_intent_pattern": "approve invoice",
  "priority": 10,
  "enabled": true,
  "steps": [
    {"id": "step_1", "description": "Fetch the invoice", "intent": "get_invoice",
     "inputs": {"invoice_id": "${invoice_id}"}},
    {"id": "step_2", "description": "Approve the invoice", "intent": "approve_invoice",
     "inputs": {"invoice_id": "${step_1}"}}
  ]
}
```

### Step kinds (any combination, validated at registration)

| Kind | Field | Behaviour |
|------|-------|-----------|
| Deterministic | `intent` / `capability` | Executes a registered capability |
| Input collection | `requires_input` + `question` | Asks the user in-chat, stores the value |
| Hybrid (dynamic step) | `"dynamic": true` | The step's plan is produced by dynamic planning at runtime |
| Building block | `workflow_ref` | Inline-expands another workflow definition |
| Template | `template` | Inline-expands a seeded workflow template |

Step inputs support `${step_X}` variable references into collected values;
step ids must be unique; every step must declare exactly one executable kind
(validated with 422 on violation).

### Lifecycle API

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/workflows` | Register (version 1) |
| GET | `/workflows` | List (filter `?enabled=`) |
| GET | `/workflows/{id}` | Get one |
| PUT | `/workflows/{id}` | Update — steps/pattern changes bump the version |
| POST | `/workflows/{id}/activate` | Enable matching |
| POST | `/workflows/{id}/deactivate` | Disable matching |
| DELETE | `/workflows/{id}` | Delete (instances preserved) |
| GET | `/workflows/{id}/instances` | List executions (`?status=`) |

### Matching

When a user request arrives, the template engine consults **both**
developer-registered workflows and seeded templates, in priority order.
Matches are composed into a single orchestration (workflow-as-building-block)
and executed step-wise. When no workflow matches, the runtime falls back to
dynamic AI planning over the registered capability catalog — the same
conversation seamlessly switches between the two.

---

## 3. Registering capabilities

Capabilities (and their providers/endpoints) are registered via the
`/api/v1/tools` API or the MCP endpoint (`/mcp`). Each tool carries risk
level, auth, schemas, cost/latency metadata, and an optional compensating
operation — all consumed dynamically by the orchestrator.

Capability changes are version-snapshotted automatically
(`capability_version` rows: registration = v1, every update bumps a version
with the full contract snapshot).

---

## 4. Python SDK (programmatic embedding)

Beyond the HTTP API and widget, Python applications can embed the runtime
directly via `NexusRuntime` — no server required:

```python
import asyncio
from nexus.runtime import NexusRuntime

async def main():
    rt = await NexusRuntime.create()

    # Register a capability (API endpoint)
    await rt.register_capability(
        name="get_invoice",
        endpoint_url="https://api.example.com/invoices/{invoice_id}",
        http_method="GET",
        purpose="Fetch an invoice by id",
        input_schema={"type": "object", "properties": {"invoice_id": {"type": "string"}}},
    )

    # Register a deterministic workflow
    await rt.register_workflow(
        name="invoice_approval",
        trigger_intent_pattern="approve invoice",
        steps=[
            {"id": "step_1", "description": "Fetch", "intent": "get_invoice",
             "inputs": {"invoice_id": "${invoice_id}"}},
        ],
    )

    # Chat (streams AgentEvent dicts — same shape as the SSE payloads)
    sid = await rt.create_session(title="Support")
    async for event in rt.chat(sid, "Approve invoice 42"):
        print(event["type"], event.get("payload", {}))

    # Long-running work
    task = await rt.create_task(task_type="workflow_run", payload={"workflow": "invoice_approval"})
    await rt.cancel_task(task["id"])

asyncio.run(main())
```

### SDK API

| Method | Purpose |
|--------|---------|
| `NexusRuntime.create()` | Wire all default components (checkpointer, registry, queue) |
| `register_capability(**fields)` | Register a tool/capability |
| `list_capabilities(**filters)` | List registered capabilities |
| `register_workflow(name, steps, ...)` | Register a deterministic workflow |
| `list_workflows(enabled=...)` | List workflow definitions |
| `delete_workflow(id)` | Delete a workflow |
| `create_session(title)` | Create a conversation session |
| `chat(session_id, message)` | Stream agent events (async iterator) |
| `create_task(task_type, payload, ...)` | Create + enqueue a background task |
| `get_task(id)` / `cancel_task(id)` | Inspect / cancel a task |
| `close()` | Release resources |

All components are injectable (runner, registries, queue, session factory)
for testing.

---

## 5. Runtime behaviour for embedded apps

| Concern | Mechanism |
|---------|-----------|
| Long-running work | `POST /api/v1/tasks` → `nexus-worker` (Redis Streams), `nexus-scheduler` for cron |
| High-risk operations | Conversational approval checkpoints (in-chat, in-widget) |
| Auth on the API | Pluggable `none` / `api_key` / `jwt` (JWKS/OIDC) via `AUTH_PROVIDER` |
| Memory | Long-term pgvector memory per session (`/api/v1/memory`) |
| Observability | SSE event stream (`final_response`, `approval_checkpoint`, `error`, `done`), execution events, audit log |

## Build & serve the widget

```bash
cd frontend
npm run build:embed        # → dist-embed/embed-widget.js
# serve dist-embed/ from any static host (CDN, S3, nginx) and reference it in
# the data-* snippet — the widget works against any Nexus API base URL.
```
