import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useLocalStorage } from "../hooks/use-local-storage";

describe("useLocalStorage", () => {
  it("should return the initial value when nothing is stored", () => {
    const { result } = renderHook(() => useLocalStorage("hl-test-1", "default"));
    expect(result.current[0]).toBe("default");
  });

  it("should update the stored value via the setter", () => {
    const { result } = renderHook(() => useLocalStorage("hl-test-2", "initial"));
    act(() => result.current[1]("updated"));
    expect(result.current[0]).toBe("updated");
  });

  it("should handle function updater", () => {
    const { result } = renderHook(() => useLocalStorage("hl-test-3", 0));
    act(() => result.current[1]((prev: number) => prev + 1));
    expect(result.current[0]).toBe(1);
  });
});
