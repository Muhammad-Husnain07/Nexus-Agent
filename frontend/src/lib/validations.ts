import { z } from "zod";

/** Validation schemas for console forms — single source of truth. */
export const toolFormSchema = z.object({
  name: z.string().trim().min(1, "Tool name is required").max(255),
  description: z.string().trim().max(2000),
  purpose: z.string().trim().max(2000),
  tool_type: z.enum(["http_api", "mcp"]),
  endpoint_url: z.string().trim().max(2048),
  mcp_server_url: z.string().trim().max(2048),
  http_method: z.enum(["GET", "POST", "PUT", "PATCH", "DELETE"]),
  auth_type: z.string().trim(),
  auth_ref: z.string().trim(),
  category: z.string().trim(),
  risk_level: z.enum(["low", "medium", "high"]),
  requires_approval: z.boolean(),
  compensating_operation: z.string().trim(),
  idempotent: z.boolean(),
  rate_limit_per_minute: z.string().trim(),
  enabled: z.boolean(),
  tags: z.string(),
  keywords: z.string(),
  aliases: z.string(),
  capabilities: z.string(),
  produces: z.string(),
  consumes: z.string(),
  related: z.string(),
  cacheable: z.boolean(),
  examples: z.array(z.object({
    user_prompt: z.string().trim().min(1, "Example prompt is required"),
    expected_tool: z.string().trim(),
    sample_input: z.string(),
  })),
  input_schema: z.string(),
  output_schema: z.string(),
  validation_rules: z.string(),
})
  .superRefine((val, ctx) => {
    if (val.tool_type === "http_api" && !val.endpoint_url.trim()) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["endpoint_url"], message: "Endpoint URL is required for HTTP tools" });
    }
    if (val.tool_type === "mcp" && !val.mcp_server_url.trim()) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["mcp_server_url"], message: "MCP server URL is required for MCP tools" });
    }
  });

export type ToolFormValues = z.infer<typeof toolFormSchema>;

/** Parse a JSON-schema textarea; returns parsed JSON or null on invalid input. */
export function parseJsonField(raw: string): Record<string, unknown> | null {
  const trimmed = raw.trim();
  if (!trimmed) return {};
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

/** Split a comma-separated list into trimmed, de-duplicated non-empty items. */
export function splitList(raw: string): string[] {
  return [...new Set(raw.split(",").map((t) => t.trim()).filter(Boolean))];
}
