import { describe, expect, it } from "vitest";
import { cn, formatDate, formatTime, truncate } from "@/lib/utils";

describe("cn", () => {
  it("merges conditional class names", () => {
    // eslint-disable-next-line no-constant-binary-expression -- verifies falsy skipping
    expect(cn("a", false && "b", "c")).toBe("a c");
  });

  it("handles undefined values", () => {
    expect(cn("a", undefined, null)).toBe("a");
  });
});

describe("truncate", () => {
  it("truncates long strings with ellipsis", () => {
    expect(truncate("abcdefghij", 5)).toBe("abcde...");
  });

  it("returns short strings unchanged", () => {
    expect(truncate("abc", 5)).toBe("abc");
  });
});

describe("formatDate", () => {
  it("formats an ISO timestamp", () => {
    const out = formatDate("2026-08-01T12:00:00Z");
    expect(out).toBeTruthy();
    expect(typeof out).toBe("string");
  });
});

describe("formatTime", () => {
  it("formats an ISO timestamp", () => {
    const out = formatTime("2026-08-01T12:00:00Z");
    expect(out).toBeTruthy();
    expect(typeof out).toBe("string");
  });
});
