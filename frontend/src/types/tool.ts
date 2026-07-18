export interface ToolExample {
  user_prompt: string
  expected_tool: string
  sample_input: Record<string, unknown>
  sample_output: Record<string, unknown>
}

export interface ToolDefinition {
  id: string
  tenant_id: string
  name: string
  description: string
  purpose: string
  tool_type: "http_api" | "mcp"
  endpoint_url: string
  mcp_server_url: string
  http_method: string
  auth_type: string
  auth_ref: string
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
  validation_rules: Record<string, unknown>
  examples: ToolExample[]
  tags: string[]
  category: string
  requires_approval: boolean
  risk_level: string
  enabled: boolean
  tenant_public?: boolean
  idempotent?: boolean
  rate_limit_per_minute?: number | null
  version: number
  created_at: string
  updated_at: string
  embedding?: number[] | null
}

export interface ToolCreatePayload {
  name: string
  description?: string
  purpose?: string
  tool_type?: "http_api" | "mcp"
  endpoint_url?: string
  mcp_server_url?: string
  http_method?: string
  auth_type?: string
  auth_ref?: string
  input_schema?: Record<string, unknown>
  output_schema?: Record<string, unknown>
  validation_rules?: Record<string, unknown>
  examples?: ToolExample[]
  tags?: string[]
  category?: string
  requires_approval?: boolean
  risk_level?: string
  enabled?: boolean
  rate_limit_per_minute?: number | null
}

export interface ToolUpdatePayload extends Partial<ToolCreatePayload> {}

export interface ToolExecutionResult {
  tool_id: string
  tool_name: string
  status: "success" | "error" | "timeout" | "validation_error" | "interrupted"
  http_status?: number | null
  data?: Record<string, unknown> | null
  error?: string | null
  duration_ms: number
  retried?: boolean
  raw_response_excerpt?: string | null
  response_headers?: Record<string, string> | null
}
