# HITL (Human-in-the-Loop) — Frontend Contract

## Overview

The agent pauses execution before any tool call that requires human approval,
emits an SSE event with the pending approval details, and waits for the
frontend to send a decision.  The same mechanism supports **intermediate
preview** feedback (approve / edit / reject a result before proceeding).

---

## SSE Event Schema

The chat SSE stream emits two event types related to human interaction:

- ``approval_required`` — emitted **before** a tool call that requires approval (tool gating). The agent pauses and waits for a decision before executing the tool.
- ``interrupt`` — emitted for generic pauses such as **final answer review** (``review_final_answer`` node) or **plan review** (``review_plan`` node). The agent presents a result and waits for feedback (approve/edit/reject) before proceeding.

Both events have the same SSE wire format but different payload structures.

### `approval_required` (tool gating)

Emitted when the agent reaches a tool call that needs human authorisation
(``hitl.requires_approval()`` returned ``True``).

```
event: approval_required
data: {"type":"approval_required","session_id":"<uuid>","payload":{...}}
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

```
event: intermediate_preview
data: {"type":"intermediate_preview","ts":"...","payload":{"text":"..."}}
```

### `interrupt` (SSE pause event)

Both ``approval_required`` and ``intermediate_preview`` pause the SSE stream.
The ``interrupt`` event is the internal LangGraph signal for these pauses.
The frontend sees the specific event type (``approval_required`` or
``intermediate_preview``) and responds accordingly.

| Event | Trigger | Agent State | User Action Required |
|-------|---------|-------------|---------------------|
| ``approval_required`` | Tool call requires pre-execution approval | Paused before tool executes | Approve/Reject/Edit inputs |
| ``intermediate_preview`` | Intermediate result ready for review | Paused after result generated | Approve/Edit/Reject result |

Both events pause the SSE stream. The agent resumes when the frontend calls
``POST /approvals/{id}/decide`` or the graph's ``Command(resume=...)``.

---

## Resume Flow

```
Frontend                      Agent API
   │                             │
    │  POST /api/v1/sessions/{session_id}/chat  │
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

**Query parameter:** `?stream=true` — returns an SSE stream of resumed execution
events (`tool_call_completed`, `final_response`, `done`) so the inline chat can
continue without reconnecting to the chat endpoint.

**Request body:** see Decision payloads table above.

**Response (stream=false, default):**
```json
{
  "status": "ok",
  "approval_id": "uuid",
  "decision": "approve"
}
```

**Response (stream=true):** SSE stream with the same event format as the
chat endpoint — `tool_call_completed`, `final_response`, `done`.

---

## Edge Cases

### Approval timeout

Pending approvals older than ``approval_timeout_hours`` (default **24 h**,
configurable via ``AgentSettings.approval_timeout_hours``) are
**auto-rejected** on read. The ``Approval`` row is updated with
``status = "rejected"`` and ``decision_payload = {"action": "reject", "reason": "timeout"}``.

### Session archived while approval pending

If the session is archived or the graph is evicted from the in-memory cache,
``POST /decide`` returns ``410 Gone``.  The frontend should treat this as
"session no longer active".

### Multiple pending approvals in the same run

The ReAct loop processes tool calls sequentially, so there is **at most one**
pending approval at a time.  The ``approvals/pending`` endpoint returns all
historical pending rows, but only the most recent one is actionable.

---

## Frontend Integration (Inline Chat Flow)

1. Connect to ``POST /api/v1/sessions/{session_id}/chat`` (SSE).
2. Listen for ``event: approval_required`` — the payload contains the tool
   name, inputs, risk level, and question.
3. Render an approval card **inline** in the chat with Approve / Reject buttons.
4. When the user clicks, call ``POST /api/v1/approvals/{approval_id}/decide?stream=true``
   with ``{"action": "approve"}`` or ``{"action": "reject"}``.
5. Parse the SSE response from the decide endpoint — it resumes execution and
   streams ``tool_call_completed``, ``final_response``, and ``done`` events.
6. Append these events to the same assistant message in the chat.
7. For **edit** actions, send ``{"action": "edit", "edited_inputs": {...}}``.
