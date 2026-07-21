export interface Tool {
  id: string;
  name: string;
  description: string;
  purpose: string;
  endpoint_url: string;
  http_method: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  tags: string[];
  category: string;
  requires_approval: boolean;
  risk_level: string;
  enabled: boolean;
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
