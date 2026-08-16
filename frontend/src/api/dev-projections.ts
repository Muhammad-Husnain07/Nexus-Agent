import type { AgentEvent } from "../types/api";

export interface DevTimelineItem {
  index: number;
  type: string;
  timestamp: string;
  phase: "planning" | "validation" | "execution" | "synthesis" | "complete" | "other";
  summary: string;
}

export interface DevExecutionRow {
  taskId: string;
  tool: string;
  status: string;
  durationMs?: number;
  retries?: number;
  cached?: boolean;
  error?: string;
}

export interface DevProjection {
  timeline: DevTimelineItem[];
  plannerTiming: Record<string, unknown> | null;
  suppressions: Array<Record<string, unknown>>;
  executions: DevExecutionRow[];
  mapDegradations: unknown[];
  evidence: Record<string, unknown> | null;
  rawEvents: AgentEvent[];
}

function payloadOf(event: AgentEvent): Record<string, unknown> {
  return (event.payload ?? {}) as Record<string, unknown>;
}

function phaseForEvent(type: string): DevTimelineItem["phase"] {
  if (["plan_created", "planner_timing", "resolution_suppressed", "intent_extracted", "tool_selected"].includes(type)) return "planning";
  if (["validation_progress", "routing_decision"].includes(type)) return "validation";
  if (["step_progress", "tool_call_completed", "node_completed", "map_degraded", "artifact_produced", "reflection_result"].includes(type)) return "execution";
  if (["final_response"].includes(type)) return "synthesis";
  if (["execution_completed", "workflow_completed", "done", "error"].includes(type)) return "complete";
  return "other";
}

function summaryForEvent(event: AgentEvent): string {
  const payload = payloadOf(event);
  if (event.type === "node_completed") return `${String(payload.node ?? "node")} · ${String(payload.duration_ms ?? 0)}ms`;
  if (event.type === "tool_call_completed") return `${String(payload.tool_name ?? "tool")} · ${String(payload.status ?? "unknown")}`;
  if (event.type === "step_progress") return `${String(payload.tool_name ?? "step")} · ${String(payload.status ?? "unknown")}`;
  if (event.type === "error") return String(payload.message ?? "error");
  if (event.type === "planner_timing") return `planner ${String(payload.latency_ms ?? 0)}ms`;
  if (event.type === "final_response") return String(payload.response_status ?? "response");
  return event.type.replaceAll("_", " ");
}

export function projectDevEvents(events: AgentEvent[]): DevProjection {
  const executions = new Map<string, DevExecutionRow>();
  let plannerTiming: Record<string, unknown> | null = null;
  let evidence: Record<string, unknown> | null = null;
  const suppressions: Array<Record<string, unknown>> = [];
  const mapDegradations: unknown[] = [];

  const timeline = events.map((event, index) => {
    const payload = payloadOf(event);
    if (event.type === "planner_timing") plannerTiming = payload;
    if (event.type === "resolution_suppressed") {
      const values = payload.suppressions;
      if (Array.isArray(values)) suppressions.push(...values.filter((v): v is Record<string, unknown> => !!v && typeof v === "object"));
    }
    if (event.type === "map_degraded") {
      const values = payload.degradations;
      if (Array.isArray(values)) mapDegradations.push(...values);
    }
    if (event.type === "final_response") {
      evidence = payload.coverage_breakdown as Record<string, unknown> | null;
    }
    if (event.type === "step_progress") {
      const taskId = String(payload.step ?? payload.tool_name ?? index);
      const previous = executions.get(taskId);
      executions.set(taskId, {
        ...previous,
        taskId,
        tool: String(payload.tool_name ?? previous?.tool ?? ""),
        status: String(payload.status ?? previous?.status ?? "queued"),
      });
    }
    if (event.type === "tool_call_completed") {
      const taskId = String(payload.task_id ?? payload.tool_name ?? index);
      const previous = executions.get(taskId);
      executions.set(taskId, {
        ...previous,
        taskId,
        tool: String(payload.tool_name ?? previous?.tool ?? ""),
        status: String(payload.status ?? "unknown"),
        durationMs: Number(payload.duration_ms ?? 0) || undefined,
        retries: Number(payload.retries ?? 0),
        cached: Boolean(payload.cached),
        error: payload.error ? String(payload.error) : undefined,
      });
    }
    return {
      index,
      type: event.type,
      timestamp: event.ts,
      phase: phaseForEvent(event.type),
      summary: summaryForEvent(event),
    };
  });

  return {
    timeline,
    plannerTiming,
    suppressions,
    executions: [...executions.values()],
    mapDegradations,
    evidence,
    rawEvents: events,
  };
}
