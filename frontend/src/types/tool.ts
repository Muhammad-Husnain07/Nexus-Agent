export interface Tool {
  id: string;
  name: string;
  description: string;
  purpose: string;
  tool_type: "http_api" | "mcp";
  endpoint_url: string;
  mcp_server_url: string;
  http_method: string;
  auth_type: string;
  auth_ref: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  validation_rules: Record<string, unknown>;
  examples: Record<string, unknown>[];
  tags: string[];
  category: string;
  risk_level: string;
  enabled: boolean;
  tenant_public: boolean;
  idempotent: boolean;
  rate_limit_per_minute: number | null;
  keywords: string[];
  aliases: string[];
  version: number;
  created_at: string;
  updated_at: string;
}

export interface ToolList {
  items: Tool[];
  total: number;
  page: number;
  page_size: number;
}
