// ── Auth ─────────────────────────────────────────────────────────────────────

export interface LoginRequest {
  email: string
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface TokenRefreshResponse {
  access_token: string
  token_type: string
}

// ── Domain models ────────────────────────────────────────────────────────────

export interface Tenant {
  id: string
  name: string
  slug: string
  status: string
  created_at: string
  settings: Record<string, unknown>
}

export interface User {
  id: string
  tenant_id: string
  email: string
  external_id?: string
  role: string
  created_at: string
}

export interface SessionRead {
  id: string
  tenant_id: string
  user_id: string
  title: string
  status: "active" | "archived"
  metadata?: Record<string, unknown>
  created_at: string
  updated_at: string
  message_count: number
}

export interface SessionList {
  items: SessionRead[]
  total: number
  page: number
  page_size: number
}

export interface MessageRead {
  id: string
  session_id: string
  role: string
  content: Record<string, unknown> | null
  tool_calls?: Record<string, unknown>[]
  parent_message_id?: string
  created_at: string
}

export interface ToolRead {
  id: string
  tenant_id: string
  name: string
  description: string
  purpose: string
  endpoint_url: string
  http_method: string
  auth_type: string
  auth_ref: string
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
  validation_rules: Record<string, unknown>
  examples: Record<string, unknown>[]
  tags: string[]
  category: string
  requires_approval: boolean
  risk_level: "low" | "medium" | "high"
  enabled: boolean
  tenant_public: boolean
  idempotent: boolean
  version: number
  created_at: string
  updated_at: string
  embedding?: number[]
  rate_limit_per_minute?: number | null
}

export interface ToolList {
  items: ToolRead[]
  total: number
  page: number
  page_size: number
}

export interface ToolExecution {
  id: string
  tool_id: string
  session_id: string
  agent_run_id?: string
  request_payload: Record<string, unknown>
  response_payload?: Record<string, unknown>
  status: string
  http_status?: number
  duration_ms: number
  error_message?: string
  retried: boolean
  created_at: string
}

export interface AgentRun {
  id: string
  session_id: string
  graph_state?: Record<string, unknown>
  plan?: Record<string, unknown>[]
  status: "running" | "completed" | "failed" | "interrupted" | "cancelled"
  started_at: string
  ended_at?: string
  total_tokens: number
  total_cost_usd: number
  checkpoint_id?: string
  created_at: string
}

export interface ApprovalRead {
  id: string
  agent_run_id: string
  tool_call: Record<string, unknown>
  status: "pending" | "approved" | "rejected" | "edited"
  reviewer_id?: string
  decision_payload?: Record<string, unknown>
  created_at: string
  decided_at?: string
}

export interface ApprovalAction {
  action: "approve" | "reject" | "edit"
  edited_inputs?: Record<string, unknown>
  comment?: string
}

// ── Chat ─────────────────────────────────────────────────────────────────────

export interface ChatRequest {
  message: string
  attachments?: string[]
  stream?: boolean
}

export interface ChatResponse {
  session_id: string
  final_response: string | null
  requires_approval: boolean
  approval_payload: Record<string, unknown> | null
  interrupted: boolean
  error: string | null
  events: AgentEvent[]
  request_id?: string
}

export interface AgentEvent {
  type: string
  ts: string
  payload: Record<string, unknown>
}

// ── Generic ──────────────────────────────────────────────────────────────────

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface ErrorResponse {
  detail: string
  error_code?: string
  request_id?: string
}

// ── Tool CRUD ────────────────────────────────────────────────────────────────

export interface ToolCreate {
  name: string
  description?: string
  purpose?: string
  endpoint_url?: string
  http_method?: string
  auth_type?: string
  auth_ref?: string
  input_schema?: Record<string, unknown>
  output_schema?: Record<string, unknown>
  validation_rules?: Record<string, unknown>
  tags?: string[]
  category?: string
  requires_approval?: boolean
  risk_level?: "low" | "medium" | "high"
  enabled?: boolean
  tenant_public?: boolean
  idempotent?: boolean
  rate_limit_per_minute?: number | null
}

export interface ToolUpdate {
  name?: string
  description?: string
  purpose?: string
  endpoint_url?: string
  http_method?: string
  auth_type?: string
  auth_ref?: string
  input_schema?: Record<string, unknown>
  output_schema?: Record<string, unknown>
  validation_rules?: Record<string, unknown>
  tags?: string[]
  category?: string
  requires_approval?: boolean
  risk_level?: "low" | "medium" | "high"
  enabled?: boolean
}

export interface ToolTestResponse {
  tool: string
  endpoint: string
  method: string
  input_validated: boolean
  mock_output: Record<string, unknown>
}

// ── Session CRUD ──────────────────────────────────────────────────────────────

export interface SessionCreate {
  title?: string
  metadata?: Record<string, unknown>
}

export interface SessionUpdate {
  title?: string
  status?: "active" | "archived"
  metadata?: Record<string, unknown>
}

export interface ForkRequest {
  message_id: string
  new_title?: string
}

export interface MessageList {
  items: MessageRead[]
  total: number
  page: number
  page_size: number
}

// ── Chat SSE ─────────────────────────────────────────────────────────────────

export type StreamStatus = "idle" | "thinking" | "executing_tool" | "awaiting_approval" | "error"

export interface ToolCallDisplay {
  id: string
  tool_name: string
  status: "running" | "success" | "error"
  inputs: Record<string, unknown>
  outputs?: Record<string, unknown>
  error?: string
  duration_ms?: number
}

export interface ChatMessage {
  id: string
  role: "user" | "assistant" | "tool" | "system"
  content: string
  tool_calls?: ToolCallDisplay[]
  created_at: string
}

export interface StreamCallbacks {
  onPlanCreated?: (payload: { steps: unknown[] }) => void
  onToolCallStarted?: (payload: { tool_name: string; inputs: Record<string, unknown> }) => void
  onToolCallCompleted?: (payload: { tool_name: string; status: string; data: unknown; error?: string }) => void
  onClarificationNeeded?: (payload: { question: string }) => void
  onIntermediatePreview?: (payload: { text: string }) => void
  onApprovalRequired?: (payload: Record<string, unknown>) => void
  onFinalResponse?: (payload: { text: string }) => void
  onError?: (payload: { message: string }) => void
  onDone?: () => void
}

// ── Observability ────────────────────────────────────────────────────────────

export interface CostSummary {
  period_days: number
  total_cost_usd: number
  total_tokens: number
  total_runs: number
}

export interface DailyCost {
  date: string
  cost_usd: number
  tokens: number
  runs: number
}

export interface ToolUsageItem {
  tool_name: string
  execution_count: number
  total_cost_usd: number
}

export interface RecentRun {
  id: string
  session_id: string
  status: string
  total_tokens: number
  total_cost_usd: number
  started_at: string
  ended_at?: string
  langsmith_url?: string
}

// ── Settings ─────────────────────────────────────────────────────────────────

export interface LlmProvider {
  name: string
  base_url: string
  models: string[]
  supports_streaming: boolean
  supports_tools: boolean
}

export interface TenantUpdate {
  name?: string
  status?: string
  settings?: Record<string, unknown>
}

export interface MetricsSnapshot {
  total_sessions: number
  total_tool_executions: number
  total_cost_usd: number
  active_users: number
  avg_response_time_ms: number
  error_rate: number
  period_start: string
  period_end: string
}
