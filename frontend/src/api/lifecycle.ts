/**
 * Run lifecycle state machine (FE Step 2) — the UI represents the backend
 * lifecycle WITHOUT inventing its own execution state. Pure reducer fed by
 * the typed SSE event stream (src/api/stream.ts) + run-status reconstruction
 * (GET /sessions/{id}/state).
 *
 * Phase map:
 *   idle → requesting → planning → validating → executing
 *       → approval | clarification | synthesizing → complete
 *   terminal: failed | cancelled | timed_out | interrupted
 */
import type {
  AgentEvent,
  ApprovalCheckpointEvent,
  ClarificationQuestionEvent,
  ExecutionStatus,
  PlanCreatedEvent,
  ResponseStatus,
  RunStatus,
} from "../types/api";

export type RunPhase =
  | "idle"
  | "requesting"
  | "planning"
  | "validating"
  | "executing"
  | "approval"
  | "clarification"
  | "synthesizing"
  | "background"
  | "complete"
  | "failed"
  | "cancelled"
  | "timed_out"
  | "interrupted";

export type StepStatus =
  | ExecutionStatus
  | "success"
  | "error"
  | "timeout"
  | "validation_error";

export interface StepState {
  taskId: string;
  tool: string;
  status: StepStatus;
  error?: string | null;
  durationMs?: number;
  cached?: boolean;
}

export interface RunLifecycle {
  phase: RunPhase;
  /** Executable plan steps (plan_created.steps: taskId -> tool). */
  plan: PlanCreatedEvent | null;
  /** Per-task execution state, merged from step_progress + tool_call_completed. */
  steps: Record<string, StepState>;
  finalText: string;
  responseStatus: ResponseStatus | string | null;
  coverage: Record<string, unknown> | null;
  approval: ApprovalCheckpointEvent | null;
  /** Server-derived expiry (epoch ms) when an approval is open. */
  approvalExpiresAt: number | null;
  clarification: ClarificationQuestionEvent | null;
  error: string | null;
  /** Bounded debug trail (node_completed, planner_timing, ...). */
  debugEvents: AgentEvent[];
  /** Total tool calls that finished successfully (for N-of-M banners). */
  succeededCount: number;
  totalCount: number;
}

export function createRunLifecycle(): RunLifecycle {
  return {
    phase: "idle",
    plan: null,
    steps: {},
    finalText: "",
    responseStatus: null,
    coverage: null,
    approval: null,
    approvalExpiresAt: null,
    clarification: null,
    error: null,
    debugEvents: [],
    succeededCount: 0,
    totalCount: 0,
  };
}

/** The exact backend budget-exceeded message shapes (runner.py). */
const WALL_TIME_EXCEEDED = /invocation budget exceeded \(wall_time\)/;
const INTERRUPTED_EXCEEDED = /invocation budget exceeded \(/;

export function reduceRunEvent(state: RunLifecycle, ev: AgentEvent): RunLifecycle {
  const next: RunLifecycle = { ...state, debugEvents: [...state.debugEvents, ev].slice(-200) };
  const payload = (ev.payload ?? {}) as Record<string, unknown>;

  switch (ev.type) {
    case "plan_created": {
      next.plan = ev.payload as unknown as PlanCreatedEvent;
      next.totalCount = Object.keys((payload.steps ?? {}) as Record<string, unknown>).length;
      if (next.phase === "idle" || next.phase === "requesting") next.phase = "planning";
      break;
    }
    case "validation_progress":
      if (next.phase === "planning") next.phase = "validating";
      break;
    case "step_progress": {
      const step = String(payload.step ?? "");
      const tool = String(payload.tool_name ?? "");
      const status = String(payload.status ?? "queued") as StepStatus;
      if (step) {
        next.steps = { ...next.steps, [step]: { ...(next.steps[step] ?? {}), taskId: step, tool, status } };
        if (status === "queued" || status === "running" || status === "retrying") {
          if (next.phase !== "approval" && next.phase !== "clarification") next.phase = "executing";
        }
        if (status === "approval") next.phase = "approval";
      }
      break;
    }
    case "tool_call_completed": {
      const tool = String(payload.tool_name ?? "");
      const status = String(payload.status ?? "success") as StepStatus;
      const taskId = String(payload.task_id ?? tool);
      next.steps = {
        ...next.steps,
        [taskId]: {
          taskId,
          tool,
          status,
          error: (payload.error as string | null | undefined) ?? null,
          durationMs: Number(payload.duration_ms ?? 0) || undefined,
          cached: Boolean(payload.cached),
        },
      };
      if (status === "success") next.succeededCount += 1;
      if (next.phase === "idle") next.phase = "executing";
      break;
    }
    case "approval_checkpoint": {
      next.approval = ev.payload as unknown as ApprovalCheckpointEvent;
      next.phase = "approval";
      break;
    }
    case "clarification_question": {
      next.clarification = ev.payload as unknown as ClarificationQuestionEvent;
      next.phase = "clarification";
      break;
    }
    case "final_response": {
      next.finalText = String(payload.text ?? next.finalText);
      next.responseStatus = (payload.response_status as ResponseStatus | undefined) ?? null;
      next.coverage = (payload.coverage_breakdown as Record<string, unknown> | undefined) ?? null;
      // approval/clarification/background are sticky — final_response does
      // not leave them (the background banner stays until the task UI).
      if (
        next.phase !== "approval" &&
        next.phase !== "clarification" &&
        next.phase !== "background"
      ) {
        next.phase = "synthesizing";
      }
      break;
    }
    case "execution_completed": {
      const status = String(payload.status ?? "");
      if (status === "cancelled") next.phase = "cancelled";
      // FE Step 3: handed to a worker — the durable task surface takes over.
      else if (status === "queued") next.phase = "background";
      else if (status === "failed" && !next.finalText) next.phase = "failed";
      else if (next.finalText) next.phase = "complete";
      break;
    }
    case "workflow_composing_progress": {
      if (payload.background === true) next.phase = "background";
      break;
    }
    case "workflow_completed":
      if (next.finalText) next.phase = "complete";
      break;
    case "error": {
      const message = String(payload.message ?? "Agent error");
      next.error = message;
      if (WALL_TIME_EXCEEDED.test(message)) next.phase = "timed_out";
      else if (INTERRUPTED_EXCEEDED.test(message)) next.phase = "interrupted";
      else if (next.phase !== "complete") next.phase = "failed";
      break;
    }
    case "done":
      if (next.phase === "synthesizing" && next.finalText) next.phase = "complete";
      break;
    default:
      break; // debug/other events only enter the trail
  }
  return next;
}

/** Explicit transitions (user action / reconstruction), not event-derived. */
export function transitionRun(state: RunLifecycle, phase: RunPhase): RunLifecycle {
  return { ...state, phase };
}

/** Set the server-derived approval expiry (epoch ms) from the read model. */
export function withApprovalExpiry(
  state: RunLifecycle,
  expiresAtEpochSeconds: number | null,
): RunLifecycle {
  return {
    ...state,
    approvalExpiresAt: expiresAtEpochSeconds != null ? expiresAtEpochSeconds * 1000 : null,
  };
}

/**
 * Refresh reconstruction: GET /sessions/{id}/state -> phase.
 * The browser is only an observer — the server owns the run.
 */
export function phaseFromRunStatus(status: RunStatus | string): RunPhase {
  switch (status) {
    case "running":
      return "executing"; // unknown sub-phase after refresh — observing
    case "completed":
      return "complete";
    case "cancelled":
      return "cancelled";
    case "timed_out":
      return "timed_out";
    case "interrupted":
      return "interrupted";
    case "failed":
      return "failed";
    default:
      return "idle";
  }
}

/** N-of-M summary for PARTIAL_SUCCESS banners. */
export function summarizeRun(lifecycle: RunLifecycle): {
  succeeded: number;
  failed: number;
  failedTools: string[];
} {
  const failedTools = Object.values(lifecycle.steps)
    .filter((s) => s.status !== "success" && s.status !== "queued" && s.status !== "running")
    .map((s) => s.tool);
  return {
    succeeded: lifecycle.succeededCount,
    failed: failedTools.length,
    failedTools: [...new Set(failedTools)],
  };
}
