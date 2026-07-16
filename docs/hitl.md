# HITL (Human-in-the-Loop) — Frontend Contract

## Overview

The agent pauses execution before any tool call that requires human approval,
emits an SSE event with the pending approval details, and waits for the
frontend to send a decision.  The same mechanism supports **intermediate
preview** feedback (approve / edit / reject a result before proceeding).

---

## SSE Event Schema

### `approval_required` (tool approval)

Emitted when the agent reaches a tool call that needs human authorisation
(``hitl.requires_approval()`` returned ``True``).

```json
{
  "event": "approval_required",
  "data": "{\"type\": \"approval_required\", \"session_id\": \"<uuid>\", \"payload\": {...}}"
}
```

The `payload` field inside ``data`` has this shape:

```json
{
  "kind": "tool_approval",
  "tool_call": {
    "name": "send_email",
    "inputs": {"to": "user@example.com", "subject": "Hello"}
  },
  "step": {
    "id": "step_2",
    "description": "Send the confirmation email",
    "is_destructive": false
  },
  "question": "Approve execution of 'send_email'?",
  "risk_level": "low"
}
```

### `interrupt` (generic pause — used by SSE stream)

When the SSE stream detects a ``pending_approval`` state update, it emits:

```json
{
  "event": "interrupt",
  "data": "{\"type\": \"approval_required\", \"session_id\": \"<uuid>\", \"payload\": {...}}"
}
```

After this event the SSE stream **closes**.  The frontend must call the
decide endpoint to resume.

### `intermediate_preview`

Emitted by the ``present_preview`` node when a step result is ready for
human review (e.g. a generated draft, computed output).

```json
{
  "event": "intermediate_preview",
  "data": "{\"type\": \"intermediate_preview\", \"ts\": \"...\", \"payload\": {\"text\": \"...\"}}"
}
```

---

## Resume Flow

```
Frontend                      Agent API
   │                             │
   │  POST /api/v1/agent/stream  │
   │────────────────────────────>│
   │                             ├── graph.astream()
   │                             │
   │  SSE: approval_required     │
   │<────────────────────────────│
   │                             │  (stream closes)
   │                             │
   │  ┌── Render approval UI ──┐ │
   │  │   "Approve send_email?" │ │
   │  │   [Approve] [Edit] [Rej]│ │
   │  └────────────────────────┘ │
   │                             │
   │  POST /api/v1/approvals/{id}/decide
   │  { "action": "approve" }    │
   │────────────────────────────>│
   │                             ├── Persist Approval row
   │                             ├── graph.astream(Command(resume=...))
   │                             ├── Tool executes
   │                             ├── Agent completes
   │  { "status": "completed" }  │
   │<────────────────────────────│
```

### Decision payloads

| Action | Body |
|--------|------|
| Approve | ``{"action": "approve"}`` |
| Reject | ``{"action": "reject", "comment": "Use a different approach"}`` |
| Edit | ``{"action": "edit", "edited_inputs": {"to": "other@example.com"}, "comment": "Wrong recipient"}`` |

---

## API Endpoints

### `GET /api/v1/approvals/pending/{session_id}`

Returns all pending (undecided) approvals for a session.  Expired approvals
(older than ``approval_timeout_hours``) are auto-rejected.

**Response:**
```json
[
  {
    "id": "uuid",
    "agent_run_id": "uuid",
    "tool_call": {"name": "send_email", "inputs": {...}},
    "status": "pending",
    "created_at": "2026-07-16T12:00:00+00:00"
  }
]
```

### `POST /api/v1/approvals/{approval_id}/decide`

Make a decision on a pending approval and resume the agent graph.

**Request body:** see Decision payloads table above.

**Response:**
```json
{
  "status": "ok",
  "approval_id": "uuid",
  "decision": "approve"
}
```

### Legacy convenience endpoints (kept for backward compatibility)

| Endpoint | Action |
|----------|--------|
| ``POST /api/v1/agent/{session_id}/approve`` | Approve |
| ``POST /api/v1/agent/{session_id}/reject`` | Reject |
| ``POST /api/v1/agent/{session_id}/edit`` | Edit (requires ``edited_inputs`` in body) |

---

## Edge Cases

### Approval timeout

Pending approvals older than ``approval_timeout_hours`` (default **24 h**,
configurable via ``AgentSettings.approval_timeout_hours``) are
**auto-rejected** when the frontend polls ``GET /pending/{session_id}``.
The ``Approval`` row is updated with ``status = "rejected"`` and
``decision_payload = {"action": "reject", "reason": "timeout"}``.

### Session archived while approval pending

If the session is archived or the graph is evicted from the in-memory cache,
``POST /decide`` returns ``410 Gone``.  The frontend should treat this as
"session no longer active".

### Multiple pending approvals in the same run

The ReAct loop processes tool calls sequentially, so there is **at most one**
pending approval at a time.  The ``approvals/pending`` endpoint returns all
historical pending rows, but only the most recent one is actionable.

---

## Frontend Integration Checklist

1. Connect to ``POST /api/v1/agent/stream`` (SSE).
2. Listen for ``event: approval_required`` and ``event: interrupt``.
3. Render an approval dialog with the ``payload.question``, tool name,
   inputs, and risk level.
4. For **edit** actions, let the user modify the ``inputs`` dict and send
   ``{"action": "edit", "edited_inputs": {...}}``.
5. Call ``POST /api/v1/approvals/{approval_id}/decide`` with the decision.
6. Reconnect to the SSE stream if resumed execution produces more events.
