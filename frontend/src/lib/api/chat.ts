import { useAuthStore } from "@/features/auth/authStore"
import type { StreamCallbacks } from "@/lib/types"

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1"

export async function streamChat(
  sessionId: string,
  message: string,
  callbacks: StreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const { access_token, tenant_id } = useAuthStore.getState()

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  }
  if (access_token) headers["Authorization"] = `Bearer ${access_token}`
  if (tenant_id) headers["X-Tenant-ID"] = tenant_id

  const response = await fetch(`${BASE_URL}/sessions/${sessionId}/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify({ message, stream: true }),
    signal,
  })

  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(body.detail || `HTTP ${response.status}`)
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error("Response body is not readable")

  const decoder = new TextDecoder()
  let buffer = ""

  const processLines = (chunk: string) => {
    buffer += chunk
    const lines = buffer.split("\n")
    buffer = lines.pop() || ""

    let currentEvent = ""
    for (const line of lines) {
      if (line.startsWith("event: ")) {
        currentEvent = line.slice(7).trim()
      } else if (line.startsWith("data: ")) {
        const raw = line.slice(6).trim()
        if (!raw) continue
        try {
          const data = JSON.parse(raw)
          dispatchEvent(currentEvent, data, callbacks)
        } catch {
          // skip unparseable data
        }
      }
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    processLines(decoder.decode(value, { stream: true }))
  }

  // Process remaining buffer
  if (buffer.trim()) {
    processLines("\n" + buffer)
  }
}

function dispatchEvent(eventType: string, data: Record<string, unknown>, cbs: StreamCallbacks) {
  switch (eventType) {
    case "plan_created":
      cbs.onPlanCreated?.(data as { steps: unknown[] })
      break
    case "tool_call_started":
      cbs.onToolCallStarted?.(data as { tool_name: string; inputs: Record<string, unknown> })
      break
    case "tool_call_completed":
      cbs.onToolCallCompleted?.(data as { tool_name: string; status: string; data: unknown; error?: string })
      break
    case "clarification_needed":
      cbs.onClarificationNeeded?.(data as { question: string })
      break
    case "intermediate_preview":
      cbs.onIntermediatePreview?.(data as { text: string })
      break
    case "approval_required":
      cbs.onApprovalRequired?.(data)
      break
    case "final_response":
      cbs.onFinalResponse?.(data as { text: string })
      break
    case "error":
      cbs.onError?.(data as { message: string })
      break
    case "done":
      cbs.onDone?.()
      break
  }
}
