# Content Studio — Nexus Agent Demo

This directory contains a complete end-to-end demonstration of Nexus Agent
orchestrating real application tools: a **Content Studio** API that the
agent manages through natural language conversations.

## Architecture

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  chat_client.py  │────▶│  Nexus Agent     │────▶│  Content Studio  │
│  (SSE / stdin)   │◀────│  (port 8000)     │◀────│  (port 8080)     │
└──────────────────┘     └──────────────────┘     └──────────────────┘
```

## Prerequisites

- Nexus Agent running on `http://localhost:8000` (see [quickstart.md](../../docs/quickstart.md))
- A JWT or API key for authentication
- Python 3.12+ with `httpx` installed (`uv add httpx` or `pip install httpx`)
- Tools must be registered — run `register_tools.py` or register via the REST API before chatting
- JWT tokens expire after 30 minutes by default — re-login or use `/auth/refresh` to get a new token

## Setup

### 1. Start the Content Studio demo app

```bash
python examples/demo_app/main.py
```

Verify: `curl http://localhost:8080/healthz` → `{"status":"ok","app":"content-studio"}`

### 2. Get an auth token

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com"}'
```

Save the returned `access_token`.

### 3. Register tools

```bash
# Edit examples/register_tools.py — set TOKEN to your access_token
# Then run:
python examples/register_tools.py
```

Expected output:
```
  ✓ list_articles
  ✓ get_article
  ✓ list_categories
  ✓ list_tags
  ✓ create_article
  ✓ update_article
  ✓ publish_article
  ✓ delete_article
  ✓ preview_article
Registered 9 tools.
```

### 4. Start chatting

```bash
python examples/chat_client.py --token <your-access-token>
```

---

## Demo Scenarios

### Scenario 1: Multi-step workflow with HITL

**User request:** "Write a draft about AI trends and publish it"

This demonstrates a **multi-step workflow** where the agent:
1. Calls `create_article` to create the draft
2. Calls `publish_article` to publish it — but this **requires approval**

Expected conversation:

```
You: Write a draft about AI trends and publish it

  [Plan] 2 step(s) planned:
    → create_article: Create a draft about AI trends
    → publish_article: Publish the draft

  [✓] create_article → success

  ⚠ Approval Required
    Tool: publish_article
    Inputs: {"article_id": "abc12345"}
    Risk: medium
  [A]pprove / [R]eject / [E]dit: a

  [✓] publish_article → success

  Draft created and published successfully!
```

### Scenario 2: Single tool — filtered listing

**User request:** "List all articles in the Tech category"

Demonstrates a **single tool call** with query parameters:

```
You: List all articles in the Tech category

  [Plan] 1 step(s) planned:
    → list_articles: List articles in Tech

  [✓] list_articles → success

  Found 2 articles in Tech:
  - AI Breakthroughs in 2026 (published)
  - Cloud Migration Strategies (published)
```

### Scenario 3: Multi-step — update then preview

**User request:** "Update the latest article's title to 'Updated: AI in 2026' then preview it"

Demonstrates a **dependency chain**: the second and third steps depend on the first step's result.

```
You: Update the latest article's title to 'Updated: AI in 2026' then preview it

  [Plan] 3 step(s) planned:
    → list_articles: Find the latest article
    → update_article: Update the article title
    → preview_article: Preview the updated article

  [✓] list_articles → success
  [✓] update_article → success
  [✓] preview_article → success

  Updated the article title and generated a preview.
```

---

## HITL Approval Behavior

| Tool | Requires Approval | Risk Level | Reason |
|------|------------------|------------|--------|
| `publish_article` | ✅ Yes | Medium | Publishing makes content visible |
| `delete_article` | ✅ Yes | High | Permanent deletion |
| `create_article` | ❌ No | Low | Non-destructive |
| `update_article` | ❌ No | Low | Reversible |
| All read tools | ❌ No | Low | Read-only |

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401 Unauthorized` from demo app | Missing auth header | Pass `Bearer demo-token` |
| `Tool not found` from agent | Tools not registered | Run `register_tools.py` |
| `Connection refused` on :8080 | Demo app not running | Start `python examples/demo_app/main.py` |
| Token expired | JWT expires in 30 min by default | Re-login |
