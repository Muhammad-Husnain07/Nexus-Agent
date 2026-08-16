/**
 * THE single status mapper — every UI surface maps backend status machines
 * through these functions. No component-specific interpretation.
 *
 * Backend value sets (nexus-agent/src/nexus):
 *  - response_status: SUCCESS | PARTIAL_SUCCESS | EXECUTION_FAILED |
 *    PLANNING_FAILED | CONVERSATIONAL
 *  - run status: running | completed | cancelled | timed_out | interrupted
 *    | failed
 *  - task status: pending | queued | running | paused | completed | failed
 *    | cancelled
 *  - execution status: queued | running | waiting | approval | retrying |
 *    completed | failed | cancelled | skipped
 *  - tool result: success | error | timeout | validation_error | interrupted
 */
import type {
  ExecutionStatus,
  ResponseStatus,
  RunStatus,
  TaskStatus,
  ToolResultStatus,
} from "../types/api";

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

export interface StatusPresentation {
  label: string;
  tone: StatusTone;
  /** User-facing explanation — never "Something went wrong." */
  description: string;
}

const RESPONSE_STATUS: Record<ResponseStatus, StatusPresentation> = {
  SUCCESS: {
    label: "Complete",
    tone: "success",
    description: "The request completed successfully.",
  },
  PARTIAL_SUCCESS: {
    label: "Partially complete",
    tone: "warning",
    description:
      "Some operations succeeded but not all — check the execution steps below.",
  },
  EXECUTION_FAILED: {
    label: "Execution failed",
    tone: "danger",
    description:
      "The planned operations could not be executed — see the error for details.",
  },
  PLANNING_FAILED: {
    label: "Planning failed",
    tone: "danger",
    description:
      "No executable plan could be produced, so no action was performed.",
  },
  CONVERSATIONAL: {
    label: "Answered",
    tone: "neutral",
    description: "A conversational response.",
  },
};

const RUN_STATUS: Record<RunStatus, StatusPresentation> = {
  running: { label: "Running", tone: "info", description: "The agent is working on the request." },
  completed: { label: "Completed", tone: "success", description: "The run finished." },
  cancelled: { label: "Cancelled", tone: "neutral", description: "The run was cancelled." },
  timed_out: {
    label: "Timed out",
    tone: "danger",
    description: "The invocation budget (wall time) was exceeded.",
  },
  interrupted: {
    label: "Interrupted",
    tone: "danger",
    description: "The invocation was interrupted (budget or client disconnect).",
  },
  failed: { label: "Failed", tone: "danger", description: "The run failed — see the error." },
};

const TASK_STATUS: Record<TaskStatus, StatusPresentation> = {
  pending: { label: "Pending", tone: "neutral", description: "Waiting to be scheduled." },
  queued: { label: "Queued", tone: "info", description: "Waiting for a worker." },
  running: { label: "Running", tone: "info", description: "A worker is executing the task." },
  paused: { label: "Paused", tone: "warning", description: "Paused by the user." },
  completed: { label: "Completed", tone: "success", description: "The task finished." },
  failed: { label: "Failed", tone: "danger", description: "The task failed after its attempts." },
  cancelled: { label: "Cancelled", tone: "neutral", description: "Cancelled by the user." },
};

const EXECUTION_STATUS: Record<ExecutionStatus, StatusPresentation> = {
  queued: { label: "Queued", tone: "neutral", description: "Waiting to execute." },
  running: { label: "Running", tone: "info", description: "Executing now." },
  waiting: { label: "Waiting", tone: "neutral", description: "Waiting for dependencies." },
  approval: {
    label: "Needs approval",
    tone: "warning",
    description: "Awaiting your decision before this operation runs.",
  },
  retrying: { label: "Retrying", tone: "warning", description: "Retrying the operation." },
  completed: { label: "Completed", tone: "success", description: "Executed successfully." },
  failed: { label: "Failed", tone: "danger", description: "The operation failed." },
  cancelled: { label: "Cancelled", tone: "neutral", description: "The operation was cancelled." },
  skipped: { label: "Skipped", tone: "neutral", description: "Skipped (e.g. unresolved input)." },
};

const TOOL_STATUS: Record<ToolResultStatus, StatusPresentation> = {
  success: { label: "Success", tone: "success", description: "The tool call succeeded." },
  error: { label: "Error", tone: "danger", description: "The tool call failed." },
  timeout: { label: "Timed out", tone: "danger", description: "The tool call exceeded its timeout." },
  validation_error: {
    label: "Validation error",
    tone: "danger",
    description: "The tool call was rejected during validation.",
  },
  interrupted: {
    label: "Interrupted",
    tone: "neutral",
    description: "The tool call was interrupted mid-flight.",
  },
};

export function mapResponseStatus(raw: string | undefined | null): StatusPresentation {
  return RESPONSE_STATUS[(raw as ResponseStatus) ?? "CONVERSATIONAL"] ?? {
    label: raw ?? "Unknown",
    tone: "neutral",
    description: "Unknown response status.",
  };
}

export function mapRunStatus(raw: string | undefined | null): StatusPresentation {
  return RUN_STATUS[(raw as RunStatus) ?? "running"] ?? {
    label: raw ?? "Unknown",
    tone: "neutral",
    description: "Unknown run status.",
  };
}

export function mapTaskStatus(raw: string | undefined | null): StatusPresentation {
  return TASK_STATUS[(raw as TaskStatus) ?? "pending"] ?? {
    label: raw ?? "Unknown",
    tone: "neutral",
    description: "Unknown task status.",
  };
}

export function mapExecutionStatus(raw: string | undefined | null): StatusPresentation {
  return EXECUTION_STATUS[(raw as ExecutionStatus) ?? "queued"] ?? {
    label: raw ?? "Unknown",
    tone: "neutral",
    description: "Unknown execution status.",
  };
}

export function mapToolStatus(raw: string | undefined | null): StatusPresentation {
  return TOOL_STATUS[(raw as ToolResultStatus) ?? "error"] ?? {
    label: raw ?? "Unknown",
    tone: "neutral",
    description: "Unknown tool status.",
  };
}
