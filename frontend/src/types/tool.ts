export interface Tool {
  id: string;
  name: string;
  description: string;
  purpose: string;
  tool_type: "http_api" | "mcp";
  endpoint_url: string;
  mcp_server_url: string | null;
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
  requires_approval: boolean;
  compensating_operation: string | null;
  enabled: boolean;
  tenant_public: boolean;
  idempotent: boolean;
  rate_limit_per_minute: number | null;
  keywords: string[];
  aliases: string[];
  capabilities: string[] | null;
  produces: string[] | null;
  consumes: string[] | null;
  related: string[] | null;
  cacheable: boolean;
  embedding: number[] | null;
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

export interface ToolSearchResult {
  tool: Tool;
  score: number;
}
