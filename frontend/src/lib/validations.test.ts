import { describe, expect, it } from "vitest";
import { parseJsonField, splitList, toolFormSchema } from "@/lib/validations";

describe("toolFormSchema", () => {
  it("accepts a valid tool form", () => {
    const result = toolFormSchema.safeParse({
      name: "get_weather",
      description: "",
      purpose: "",
      tool_type: "http_api",
      endpoint_url: "https://api.example.com/v1/weather",
      mcp_server_url: "",
      http_method: "GET",
      auth_type: "none",
      auth_ref: "",
      category: "general",
      risk_level: "low",
      requires_approval: false,
      compensating_operation: "",
      idempotent: false,
      rate_limit_per_minute: "",
      enabled: true,
      tags: "",
      keywords: "",
      aliases: "",
      capabilities: "",
      produces: "",
      consumes: "",
      related: "",
      cacheable: true,
      examples: [
        { user_prompt: "Weather in Tokyo", expected_tool: "get_weather", sample_input: '{"city": "Tokyo"}' },
      ],
      input_schema: "{}",
      output_schema: "{}",
      validation_rules: "{}",
    });
    expect(result.success).toBe(true);
  });

  it("accepts an MCP tool with a server URL", () => {
    const result = toolFormSchema.safeParse({
      name: "mcp_search",
      description: "",
      purpose: "",
      tool_type: "mcp",
      endpoint_url: "",
      mcp_server_url: "http://localhost:9000/sse",
      http_method: "GET",
      auth_type: "none",
      auth_ref: "",
      category: "general",
      risk_level: "low",
      requires_approval: false,
      compensating_operation: "",
      idempotent: false,
      rate_limit_per_minute: "",
      enabled: true,
      tags: "",
      keywords: "",
      aliases: "",
      capabilities: "",
      produces: "",
      consumes: "",
      related: "",
      cacheable: true,
      examples: [],
      input_schema: "{}",
      output_schema: "{}",
      validation_rules: "{}",
    });
    expect(result.success).toBe(true);
  });

  it("rejects an MCP tool without a server URL", () => {
    const result = toolFormSchema.safeParse({
      name: "mcp_search",
      description: "",
      purpose: "",
      tool_type: "mcp",
      endpoint_url: "",
      mcp_server_url: "",
      http_method: "GET",
      auth_type: "none",
      auth_ref: "",
      category: "general",
      risk_level: "low",
      requires_approval: false,
      compensating_operation: "",
      idempotent: false,
      rate_limit_per_minute: "",
      enabled: true,
      tags: "",
      keywords: "",
      aliases: "",
      capabilities: "",
      produces: "",
      consumes: "",
      related: "",
      cacheable: true,
      examples: [],
      input_schema: "{}",
      output_schema: "{}",
      validation_rules: "{}",
    });
    expect(result.success).toBe(false);
  });

  it("rejects a missing name", () => {
    const result = toolFormSchema.safeParse({
      name: "  ",
      endpoint_url: "https://x.example.com",
      http_method: "GET",
      auth_type: "none",
      category: "general",
      risk_level: "low",
      enabled: true,
    });
    expect(result.success).toBe(false);
  });

  it("rejects an invalid http method", () => {
    const result = toolFormSchema.safeParse({
      name: "t",
      endpoint_url: "https://x.example.com",
      http_method: "FETCH",
      auth_type: "none",
      category: "general",
      risk_level: "low",
      enabled: true,
    });
    expect(result.success).toBe(false);
  });
});

describe("parseJsonField", () => {
  it("parses valid JSON", () => {
    expect(parseJsonField('{"type":"object"}')).toEqual({ type: "object" });
  });

  it("returns {} for empty input", () => {
    expect(parseJsonField("  ")).toEqual({});
  });

  it("returns null for invalid JSON", () => {
    expect(parseJsonField("{not json")).toBeNull();
  });

  it("returns null for non-object JSON", () => {
    expect(parseJsonField("[1,2]")).toBeNull();
  });
});

describe("splitList", () => {
  it("splits, trims, and dedupes", () => {
    expect(splitList("a, b, a , c")).toEqual(["a", "b", "c"]);
  });

  it("returns [] for empty input", () => {
    expect(splitList(" , , ")).toEqual([]);
  });
});
