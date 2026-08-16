import { describe, expect, it } from "vitest";

import { projectDevEvents } from "./dev-projections";

const event = (type: string, payload: Record<string, unknown>) => ({
  type,
  ts: "2026-01-01T00:00:00Z",
  payload,
});

describe("developer-console projections", () => {
  it("projects planner timing, suppressions and execution rows", () => {
    const projection = projectDevEvents([
      event("planner_timing", { latency_ms: 1200, chunk_timing: { max_chunk_ms: 900 } }),
      event("resolution_suppressed", { suppressions: [{ capability: "web", reason: "generic" }] }),
      event("step_progress", { step: "t1", tool_name: "geocode_location", status: "running" }),
      event("tool_call_completed", { task_id: "t1", tool_name: "geocode_location", status: "success", duration_ms: 42, cached: true, retries: 1 }),
      event("final_response", { response_status: "PARTIAL_SUCCESS", coverage_breakdown: { evidence_required: 2 } }),
    ]);
    expect(projection.plannerTiming).toMatchObject({ latency_ms: 1200 });
    expect(projection.suppressions[0]).toMatchObject({ capability: "web" });
    expect(projection.executions[0]).toMatchObject({ taskId: "t1", status: "success", cached: true });
    expect(projection.evidence).toMatchObject({ evidence_required: 2 });
    expect(projection.timeline).toHaveLength(5);
  });

  it("keeps raw events and map degradations without inventing values", () => {
    const raw = event("map_degraded", { degradations: [{ node: "m", reason: "missing collection" }] });
    const projection = projectDevEvents([raw]);
    expect(projection.rawEvents).toEqual([raw]);
    expect(projection.mapDegradations).toEqual([{ node: "m", reason: "missing collection" }]);
    expect(projection.timeline[0].phase).toBe("execution");
  });
});
