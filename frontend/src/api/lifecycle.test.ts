import { describe, expect, it } from "vitest";

import {
  createRunLifecycle,
  phaseFromRunStatus,
  reduceRunEvent,
  summarizeRun,
  transitionRun,
} from "./lifecycle";
import type { AgentEvent } from "../types/api";

const ev = (type: string, payload: Record<string, unknown> = {}): AgentEvent => ({
  type,
  ts: "2026-01-01T00:00:00Z",
  payload,
});

describe("run lifecycle reducer (UI represents backend, invents nothing)", () => {
  it("walks the full happy-path phase ladder", () => {
    let s = createRunLifecycle();
    s = reduceRunEvent(s, ev("plan_created", { steps: { t1: "search_books", t2: "define_word" }, waves: 1 }));
    expect(s.phase).toBe("planning");
    expect(s.totalCount).toBe(2);
    s = reduceRunEvent(s, ev("validation_progress", { total_checked: 2 }));
    expect(s.phase).toBe("validating");
    s = reduceRunEvent(s, ev("step_progress", { step: "t1", status: "queued", tool_name: "search_books" }));
    s = reduceRunEvent(s, ev("step_progress", { step: "t2", status: "running", tool_name: "define_word" }));
    expect(s.phase).toBe("executing");
    s = reduceRunEvent(s, ev("tool_call_completed", { task_id: "t1", tool_name: "search_books", status: "success", duration_ms: 42, cached: false }));
    s = reduceRunEvent(s, ev("tool_call_completed", { task_id: "t2", tool_name: "define_word", status: "success", duration_ms: 7, cached: false }));
    expect(s.steps["t1"].status).toBe("success");
    expect(s.succeededCount).toBe(2);
    s = reduceRunEvent(s, ev("final_response", { text: "Done", response_status: "SUCCESS", coverage_breakdown: {} }));
    expect(s.phase).toBe("synthesizing");
    s = reduceRunEvent(s, ev("execution_completed", { status: "completed", final_response: "Done" }));
    expect(s.phase).toBe("complete");
    expect(s.finalText).toBe("Done");
  });

  it("enters approval on approval_checkpoint and keeps steps", () => {
    let s = reduceRunEvent(createRunLifecycle(), ev("approval_checkpoint", {
      message: "Approve?", tools: ["delete_users"], policy: "risky", context: "POST delete_users", options: ["approve", "reject"],
    }));
    expect(s.phase).toBe("approval");
    expect(s.approval?.tools).toEqual(["delete_users"]);
    // final_response while approval pending does not overwrite the phase
    s = reduceRunEvent(s, ev("final_response", { text: "Waiting", response_status: "SUCCESS" }));
    expect(s.phase).toBe("approval");
  });

  it("enters clarification on clarification_question", () => {
    const s = reduceRunEvent(createRunLifecycle(), ev("clarification_question", { question: "Which city?", slots_filled: 1 }));
    expect(s.phase).toBe("clarification");
    expect(s.clarification?.question).toBe("Which city?");
  });

  it("classifies wall_time budget errors as timed_out", () => {
    const s = reduceRunEvent(createRunLifecycle(), ev("error", { message: "invocation budget exceeded (wall_time)" }));
    expect(s.phase).toBe("timed_out");
    expect(s.error).toContain("wall_time");
  });

  it("classifies other budget errors as interrupted", () => {
    const s = reduceRunEvent(createRunLifecycle(), ev("error", { message: "invocation budget exceeded (llm_calls)" }));
    expect(s.phase).toBe("interrupted");
  });

  it("classifies plain errors as failed (never silent)", () => {
    const s = reduceRunEvent(createRunLifecycle(), ev("error", { message: "tool exploded" }));
    expect(s.phase).toBe("failed");
    expect(s.error).toBe("tool exploded");
  });

  it("marks cancelled via execution_completed", () => {
    let s = reduceRunEvent(createRunLifecycle(), ev("plan_created", { steps: {} }));
    s = reduceRunEvent(s, ev("execution_completed", { status: "cancelled" }));
    expect(s.phase).toBe("cancelled");
  });

  it("summarizes N-of-M for partial success", () => {
    let s = createRunLifecycle();
    s = reduceRunEvent(s, ev("plan_created", { steps: { a: "w", b: "g", c: "b", d: "u" } }));
    s = reduceRunEvent(s, ev("tool_call_completed", { task_id: "a", tool_name: "w", status: "success" }));
    s = reduceRunEvent(s, ev("tool_call_completed", { task_id: "b", tool_name: "g", status: "success" }));
    s = reduceRunEvent(s, ev("tool_call_completed", { task_id: "c", tool_name: "b", status: "success" }));
    s = reduceRunEvent(s, ev("tool_call_completed", { task_id: "d", tool_name: "u", status: "error", error: "boom" }));
    s = reduceRunEvent(s, ev("final_response", { text: "partial", response_status: "PARTIAL_SUCCESS" }));
    const sum = summarizeRun(s);
    expect(sum.succeeded).toBe(3);
    expect(sum.failed).toBe(1);
    expect(sum.failedTools).toEqual(["u"]);
  });

  it("derives phases from run status for refresh reconstruction", () => {
    expect(phaseFromRunStatus("running")).toBe("executing");
    expect(phaseFromRunStatus("completed")).toBe("complete");
    expect(phaseFromRunStatus("timed_out")).toBe("timed_out");
    expect(phaseFromRunStatus("interrupted")).toBe("interrupted");
    expect(phaseFromRunStatus("cancelled")).toBe("cancelled");
    expect(phaseFromRunStatus("failed")).toBe("failed");
  });

  it("keeps a bounded debug trail and ignores unknown events", () => {
    let s = createRunLifecycle();
    for (let i = 0; i < 250; i++) s = reduceRunEvent(s, ev("node_completed", { node: `n${i}` }));
    expect(s.debugEvents.length).toBeLessThanOrEqual(200);
    expect(s.phase).toBe("idle");
  });

  it("supports explicit transitions (cancel from UI)", () => {
    let s = reduceRunEvent(createRunLifecycle(), ev("plan_created", { steps: {} }));
    s = transitionRun(s, "cancelled");
    expect(s.phase).toBe("cancelled");
  });
});
