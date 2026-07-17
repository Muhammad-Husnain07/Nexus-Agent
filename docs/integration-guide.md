# Integration Guide

This guide covers embedding the Nexus Agent chatbot in your application: authentication, SSE/WebSocket clients, event reference, and HITL UX patterns.

---

## Authentication

### JWT Token Flow

```bash
# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com"}'
# → {"access_token":"eyJ...","refresh_token":"eyJ...","token_type":"bearer"}

# Use in every request
Authorization: Bearer eyJ...
```

### API Key Flow

```bash
# Set the key via the API or admin panel
Authorization: Bearer eyJ...

# Use the API key header instead
X-API-Key: nxs_abc123...
```

---

## SSE Client (JavaScript)

Use the native `EventSource` API. SSE is the recommended method for unidirectional streaming from agent to frontend.

```html
<!DOCTYPE html>
<html>
<body>
  <div id="chat"></div>
  <script>
    const SESSION_ID = '<session-uuid>';
    const TOKEN = '<jwt-or-api-key>';
    const chat = document.getElementById('chat');

    async function sendMessage(message) {
      const response = await fetch(
        `http://localhost:8000/api/v1/sessions/${SESSION_ID}/chat`,
        {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${TOKEN}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ message, stream: true }),
        }
      );

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            const eventType = line.slice(7);
            // Next line with "data: " will have the payload
          } else if (line.startsWith('data: ')) {
            const data = JSON.parse(line.slice(6));
            renderEvent(data);
          }
        }
      }
    }

    function renderEvent(event) {
      if (event.type === 'plan_created') {
        chat.innerHTML += `<p><b>Plan:</b> ${JSON.stringify(event.payload.steps)}</p>`;
      } else if (event.type === 'final_response') {
        chat.innerHTML += `<p><b>Agent:</b> ${event.payload.text}</p>`;
      } else if (event.type === 'approval_required') {
        showApprovalUI(event.payload);
      } else if (event.type === 'clarification_needed') {
        chat.innerHTML += `<p><i>Agent asks:</i> ${event.payload.question}</p>`;
      }
    }
  </script>
</body>
</html>
```

---

## SSE Client (Python — httpx)

```python
import json
import httpx

async def stream_chat(session_id: str, message: str, token: str):
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            f"http://localhost:8000/api/v1/sessions/{session_id}/chat",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"message": message, "stream": True},
        ) as response:
            buffer = ""
            async for chunk in response.aiter_bytes():
                buffer += chunk.decode()
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.startswith("event: "):
                        event_type = line[7:]
                    elif line.startswith("data: "):
                        data = json.loads(line[6:])
                        yield event_type, data
```

---

## WebSocket Client (JavaScript)

For bidirectional communication:

```javascript
const ws = new WebSocket(
  `ws://localhost:8000/api/v1/sessions/${SESSION_ID}/ws`
);

ws.onopen = () => {
  ws.send(JSON.stringify({ type: 'message', content: 'Hello!' }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'error') {
    console.error(data.payload.message);
  } else if (data.type === 'done') {
    ws.close();
  }
};
```

---

## Event Schema Reference

Every SSE event has the format:
```
event: <type>
data: {"type":"<type>","ts":"ISO-8601","payload":{...}}
```

### Event Types

| Event | When | Payload |
|-------|------|---------|
| `plan_created` | Agent creates a plan | `{"steps": [{"id","description","tool_name","depends_on"}]}` |
| `tool_call_started` | Agent begins tool execution | `{"tool_name": "str", "arguments": {...}}` |
| `tool_call_completed` | Tool execution finished | `{"tool_name": "str", "status": "success", "data": {...}}` |
| `clarification_needed` | Agent needs more information | `{"question": "What email address?"}` |
| `approval_required` | Tool requires HITL approval | See [HITL docs](hitl.md) for full payload |
| `intermediate_preview` | Result ready for human review | `{"text": "..."}` |
| `final_response` | Agent completes its turn | `{"text": "The email was sent."}` |
| `error` | An error occurred | `{"message": "Tool timeout"}`, `{"errors": [...]}` |
| `done` | Stream complete | `{}` |

---

## HITL UX Patterns

### Rendering Approval Requests

When you receive an `approval_required` event, the SSE stream **closes**. You must:

1. Parse the payload to get the tool call details
2. Render an approval dialog showing: tool name, inputs, risk level
3. On user decision, call the decide endpoint

```javascript
async function showApprovalUI(payload) {
  const { tool_call, risk_level, question } = payload;

  // Render dialog
  const approved = confirm(
    `${question}\n\n` +
    `Tool: ${tool_call.name}\n` +
    `Inputs: ${JSON.stringify(tool_call.inputs)}\n` +
    `Risk: ${risk_level}\n\n` +
    `Click OK to approve, Cancel to reject`
  );

  if (approved) {
    await decideApproval(approvalId, 'approve');
  } else {
    await decideApproval(approvalId, 'reject', 'User declined');
  }
}

async function decideApproval(approvalId, action, comment) {
  await fetch(`http://localhost:8000/api/v1/approvals/${approvalId}/decide`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${TOKEN}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ action, comment }),
  });
  // Reconnect to SSE stream to get remaining events
  sendMessage(document.getElementById('input').value);
}
```

### Decision Payloads

| Action | Request Body |
|--------|-------------|
| Approve | `{"action": "approve"}` |
| Reject | `{"action": "reject", "comment": "Reason"}` |
| Edit | `{"action": "edit", "edited_inputs": {"field": "new-value"}}` |

### Approval Timeout

Pending approvals auto-reject after `approval_timeout_hours` (default 24h). Poll:
```bash
GET /api/v1/approvals/pending/{session_id}
```
Expired approvals return with `status: "rejected"` and `decision_payload: {"reason": "timeout"}`.

---

## Session Management

```bash
# Create session
POST /api/v1/sessions
{"title": "Customer support chat"}

# List sessions
GET /api/v1/sessions?status=active&page=1&page_size=20

# Get session
GET /api/v1/sessions/{id}

# Fork session (branch conversation)
POST /api/v1/sessions/{id}/fork
{"message_id": "uuid", "new_title": "What-if scenario"}

# Archive session
DELETE /api/v1/sessions/{id}

# Get messages
GET /api/v1/sessions/{id}/messages?page=1&page_size=50
```

---

## Multi-Tenant Headers

```bash
# Set tenant context via header
X-Tenant-ID: 11111111-1111-4111-8111-111111111111
```

All queries are automatically scoped to the tenant. See [Architecture](architecture.md) for details.
