export interface ChatMessage {
  id: string
  session_id: string
  role: "user" | "agent" | "tool" | "system"
  content: string
  tool_call?: ToolCallInfo
  hitl_request?: HITLRequest
  created_at: string
}

export interface ToolCallInfo {
  tool_name: string
  arguments: Record<string, unknown>
  status: "pending" | "running" | "success" | "error"
  result?: Record<string, unknown> | null
  duration_ms?: number
  error?: string | null
}

export interface HITLRequest {
  tool_name: string
  inputs: Record<string, unknown>
  reason: string
  status: "pending" | "approved" | "rejected"
}

export interface SessionInfo {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}
