// Backend API response types — mirrors nexus-agent/src/nexus/agent/schemas.py

export interface ToolRead {
  id: string
  name: string
  description: string
  purpose: string
  endpoint_url: string
  http_method: string
  auth_type: string
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
  tags: string[]
  category: string
  requires_approval: boolean
  risk_level: "low" | "medium" | "high"
  enabled: boolean
  version: number
  embedding?: number[]
}

export interface SessionRead {
  id: string
  tenant_id: string
  user_id: string
  title: string
  status: "active" | "archived"
  created_at: string
  updated_at: string
}

export interface ChatResponse {
  session_id: string
  final_response: string | null
  requires_approval: boolean
  approval_payload: Record<string, unknown> | null
  interrupted: boolean
  error: string | null
  events: AgentEvent[]
}

export interface AgentEvent {
  type: string
  ts: string
  payload: Record<string, unknown>
}

export interface ApprovalRead {
  id: string
  agent_run_id: string
  tool_call: Record<string, unknown>
  status: "pending" | "approved" | "rejected" | "edited"
  created_at: string
  decided_at?: string
  decision_payload?: Record<string, unknown>
}

export interface ApprovalAction {
  action: "approve" | "reject" | "edit"
  edited_inputs?: Record<string, unknown>
  comment?: string
}
