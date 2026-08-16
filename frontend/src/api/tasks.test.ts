import { describe, expect, it } from "vitest";

import { isTaskActive, taskListNeedsPolling } from "./tasks";
import { createRunLifecycle, reduceRunEvent } from "./lifecycle";

const ev = (type: string, payload: Record<string, unknown> = {}) => ({
  type,
  ts: "2026-01-01T00:00:00Z",
  payload,
});

describe("task polling bounds (FE Step 3: bounded, no duplicate)", () => {
  it("treats pending/queued/running as active", () => {
    expect(isTaskActive("queued")).toBe(true);
    expect(isTaskActive("running")).toBe(true);
    expect(isTaskActive("pending")).toBe(true);
    expect(isTaskActive("paused")).toBe(false);
    expect(isTaskActive("completed")).toBe(false);
    expect(isTaskActive("failed")).toBe(false);
    expect(isTaskActive("cancelled")).toBe(false);
    expect(isTaskActive(undefined)).toBe(false);
  });

  it("polls a list only while any task is active", () => {
    expect(taskListNeedsPolling([])).toBe(false);
    expect(taskListNeedsPolling(undefined)).toBe(false);
    expect(taskListNeedsPolling([{ status: "completed" } as never])).toBe(false);
    expect(taskListNeedsPolling([{ status: "running" } as never])).toBe(true);
    expect(
      taskListNeedsPolling([{ status: "completed" } as never, { status: "queued" } as never]),
    ).toBe(true);
  });
});

describe("background phase (FE Step 3)", () => {
  it("enters background on execution_completed queued", () => {
    let s = reduceRunEvent(createRunLifecycle(), ev("plan_created", { steps: {} }));
    s = reduceRunEvent(s, ev("execution_completed", { status: "queued" }));
    expect(s.phase).toBe("background");
  });

  it("enters background on workflow_composing_progress with background flag", () => {
    let s = createRunLifecycle();
    s = reduceRunEvent(s, ev("workflow_composing_progress", { phase: "estimate", background: true }));
    expect(s.phase).toBe("background");
  });

  it("keeps final text when the background run later reports it", () => {
    let s = reduceRunEvent(createRunLifecycle(), ev("plan_created", { steps: {} }));
    s = reduceRunEvent(s, ev("execution_completed", { status: "queued" }));
    s = reduceRunEvent(s, ev("final_response", { text: "done in background", response_status: "SUCCESS" }));
    expect(s.phase).toBe("background");
    expect(s.finalText).toBe("done in background");
  });
});
