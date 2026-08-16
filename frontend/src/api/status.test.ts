import { describe, expect, it } from "vitest";

import {
  mapExecutionStatus,
  mapResponseStatus,
  mapRunStatus,
  mapTaskStatus,
} from "./status";

describe("status mapper (single interpretation of backend machines)", () => {
  it("maps every response status distinctly", () => {
    expect(mapResponseStatus("SUCCESS").tone).toBe("success");
    expect(mapResponseStatus("PARTIAL_SUCCESS").tone).toBe("warning");
    expect(mapResponseStatus("PARTIAL_SUCCESS").label).toBe("Partially complete");
    expect(mapResponseStatus("EXECUTION_FAILED").tone).toBe("danger");
    expect(mapResponseStatus("PLANNING_FAILED").label).toBe("Planning failed");
    expect(mapResponseStatus("CONVERSATIONAL").tone).toBe("neutral");
  });

  it("never produces 'Something went wrong' — descriptions are specific", () => {
    for (const raw of ["SUCCESS", "PARTIAL_SUCCESS", "EXECUTION_FAILED", "PLANNING_FAILED"]) {
      expect(mapResponseStatus(raw).description).not.toMatch(/something went wrong/i);
    }
  });

  it("falls back gracefully for unknown values", () => {
    expect(mapResponseStatus("WEIRD").label).toBe("WEIRD");
    expect(mapResponseStatus(null).label).toBe("Answered"); // CONVERSATIONAL default
  });

  it("maps run statuses including the terminal-abnormal set", () => {
    expect(mapRunStatus("running").tone).toBe("info");
    expect(mapRunStatus("completed").tone).toBe("success");
    expect(mapRunStatus("timed_out").label).toBe("Timed out");
    expect(mapRunStatus("interrupted").label).toBe("Interrupted");
    expect(mapRunStatus("cancelled").label).toBe("Cancelled");
    expect(mapRunStatus("failed").tone).toBe("danger");
  });

  it("maps task statuses", () => {
    expect(mapTaskStatus("queued").label).toBe("Queued");
    expect(mapTaskStatus("running").label).toBe("Running");
    expect(mapTaskStatus("paused").tone).toBe("warning");
    expect(mapTaskStatus("failed").tone).toBe("danger");
  });

  it("maps execution statuses incl. approval", () => {
    expect(mapExecutionStatus("approval").label).toBe("Needs approval");
    expect(mapExecutionStatus("approval").tone).toBe("warning");
    expect(mapExecutionStatus("skipped").label).toBe("Skipped");
    expect(mapExecutionStatus("retrying").tone).toBe("warning");
  });
});
