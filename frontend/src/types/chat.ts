export interface Session {
  id: string;
  tenant_id: string;
  user_id: string;
  title: string;
  status: "active" | "archived";
  message_count?: number;
  token_count?: number;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "tool" | "system";
  content: string;
  tool_calls?: ToolCall[];
  tool_results?: ToolResult[];
  created_at: string;
}

export interface ToolCall {
  id: string;
  type: "function";
  function: {
    name: string;
    arguments: string;
  };
}

export interface ToolResult {
  tool_name: string;
  status: "success" | "error" | "pending";
  data?: unknown;
  error?: string;
  duration_ms?: number;
}

export interface ChatRequest {
  message: string;
  stream?: boolean;
}

export interface ChatResponse {
  session_id: string;
  final_response?: string;
  requires_approval?: boolean;
  approval_payload?: ApprovalPayload;
  interrupted?: boolean;
  error?: string;
  events: AgentEvent[];
}

export interface AgentEvent {
  type: string;
  ts: string;
  payload: Record<string, unknown>;
}

export interface ApprovalPayload {
  tool_name: string;
  inputs: Record<string, unknown>;
  approval_id: string;
  risk_level?: string;
}

export interface StreamEvent {
  event: string;
  data: string;
}
