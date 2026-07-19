import { describe, it, expect } from "vitest";

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return s.slice(0, max - 3) + "...";
}

describe("Utility functions", () => {
  it("should format dates correctly", () => {
    const date = new Date("2026-07-19T10:00:00Z");
    expect(date.toISOString()).toContain("2026-07-19");
  });

  it("should handle number formatting", () => {
    const n = 1234567.89;
    expect(n.toLocaleString("en-US")).toBe("1,234,567.89");
  });

  it("should truncate strings when over max length", () => {
    expect(truncate("Hi", 10)).toBe("Hi");
    expect(truncate("HelloWorldExtra", 11)).toBe("HelloWor...");
  });

  it("should keep strings under max length unchanged", () => {
    expect(truncate("Hi", 10)).toBe("Hi");
  });

  it("should parse JSON", () => {
    const obj = JSON.parse('{"name":"test","value":42}');
    expect(obj.name).toBe("test");
    expect(obj.value).toBe(42);
  });
});
