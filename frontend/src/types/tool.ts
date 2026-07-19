export interface ToolDefinition {
  id: string;
  tenant_id: string;
  name: string;
  description: string;
  purpose?: string;
  endpoint_url: string;
  http_method: string;
  auth_type?: string;
  auth_ref?: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  validation_rules?: Record<string, unknown>;
  examples?: ToolExample[];
  tags: string[];
  category: string;
  requires_approval: boolean;
  risk_level: "low" | "medium" | "high" | "critical";
  enabled: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface ToolExample {
  name?: string;
  prompt?: string;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
}

export interface ToolCreatePayload {
  name: string;
  description: string;
  purpose?: string;
  endpoint_url: string;
  http_method: string;
  auth_type?: string;
  auth_ref?: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  validation_rules?: Record<string, unknown>;
  examples?: ToolExample[];
  tags?: string[];
  category?: string;
  requires_approval?: boolean;
  risk_level?: "low" | "medium" | "high" | "critical";
  enabled?: boolean;
}

export interface ToolVersion {
  id: string;
  tool_id: string;
  version: number;
  snapshot: Record<string, unknown>;
  changed_by?: string;
  change_comment?: string;
  created_at: string;
}

export interface ToolSearchResult {
  tool: ToolDefinition;
  score: number;
}
