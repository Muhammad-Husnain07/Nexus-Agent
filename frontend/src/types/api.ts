/**
 * Canonical API contracts — the ONLY representation of backend responses.
 *
 * Mirrors nexus-agent/src/nexus (see nexus-agent/docs/frontend-e2e-plan.md).
 * Runtime-validated at the client boundary via src/api/contracts.ts (zod) —
 * drift between backend schemas and these types fails tests, never runtime.
 */

/** Backend middleware error: {error: {code, message, request_id}}. */
export interface BackendErrorBody {
  error?: { code?: string; message?: string; request_id?: string };
  detail?: string;
  error_code?: string;
}

/** Normalized client error (produced by the API client interceptor). */
export interface ApiError {
  code: string;
  message: string;
  request_id?: string;
  status?: number;
}

export interface ApiResponse<T> {
  data?: T;
  error?: ApiError;
}

/* ── Status machines (single source: src/api/status.ts mapper) ─────────── */

export type ResponseStatus =
  | "SUCCESS"
  | "PARTIAL_SUCCESS"
  | "EXECUTION_FAILED"
  | "PLANNING_FAILED"
  | "CONVERSATIONAL";

export type RunStatus =
  | "running"
  | "completed"
  | "cancelled"
  | "timed_out"
  | "interrupted"
  | "failed";

export type TaskStatus =
  | "pending"
  | "queued"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export type ExecutionStatus =
  | "queued"
  | "running"
  | "waiting"
  | "approval"
  | "retrying"
  | "completed"
  | "failed"
  | "cancelled"
  | "skipped";

export type ToolResultStatus =
  | "success"
  | "error"
  | "timeout"
  | "validation_error"
  | "interrupted";

/* ── Chat ──────────────────────────────────────────────────────────────── */

export interface ChatRequest {
  message: string;
  attachments?: string[];
  stream?: boolean;
}

export interface ChatResponse {
  session_id: string;
  final_response: string | null;
  requires_approval: boolean;
  approval_payload: Record<string, unknown> | null;
  interrupted: boolean;
  error: string | null;
  events: AgentEvent[];
  request_id?: string | null;
}

/** Open approval checkpoint read model (GET /sessions/{id}/state). */
export interface ApprovalPending {
  policy: string;
  step: string;
  message: string;
  context: string;
  tools: string[];
  tool_details: Record<string, unknown>;
  requested_at: number | null;
  expires_at: number | null;
  expired: boolean;
}

export interface AgentStateResponse {
  session_id: string;
  status: RunStatus;
  current_node: string | null;
  final_response: string | null;
  error?: string | null;
  approval_pending: ApprovalPending | null;
}

/* ── SSE event envelope + inventory ────────────────────────────────────── */

export interface AgentEvent<T = Record<string, unknown>> {
  type: string;
  ts: string;
  payload: T;
}

export interface NodeCompletedEvent {
  node: string;
  duration_ms: number;
  has_output: boolean;
  cost_usd: number;
  retries: number;
}

export interface FinalResponseEvent {
  text: string;
  cost_usd: number;
  latency_ms: number;
  response_status: ResponseStatus | string;
  coverage_breakdown: Record<string, unknown>;
}

export interface PlanCreatedEvent {
  steps: Record<string, string>;
  waves: number;
  strategy: string;
  estimated_cost_usd: number;
  estimated_latency_ms: number;
}

export interface StepProgressEvent {
  step: string;
  status: ExecutionStatus;
  text: string;
  tool_name: string;
}

export interface ToolCallCompletedEvent {
  tool_name: string;
  status: ToolResultStatus | string;
  data?: unknown;
  error?: string | null;
  task_id?: string;
  duration_ms: number;
  retries: number;
  cached: boolean;
}

export interface ErrorEvent {
  message: string;
}

export interface ApprovalCheckpointEvent {
  message: string;
  tools: string[];
  policy: string;
  context: string;
  options: string[];
}

export interface ClarificationQuestionEvent {
  question: string;
  slots_filled: number;
}

export interface ExecutionCompletedEvent {
  status: ExecutionStatus | string;
  final_response: string;
  cost_usd: number;
  duration_ms: number;
}

/** Events a user-facing UI renders; the rest go to the developer console. */
export const USER_VISIBLE_EVENTS: ReadonlySet<string> = new Set([
  "intent_extracted",
  "plan_created",
  "step_progress",
  "tool_call_completed",
  "approval_checkpoint",
  "clarification_question",
  "final_response",
  "execution_completed",
  "error",
  "workflow_composing_progress",
  "workflow_step_started",
  "workflow_input_required",
  "workflow_paused",
  "workflow_cancelled",
  "workflow_completed",
  "tool_selected",
]);

/* ── Messages / sessions ───────────────────────────────────────────────── */

export interface MessageContent {
  text?: string;
  [key: string]: unknown;
}

export interface ChatMessage {
  id: string;
  session_id?: string;
  parent_id?: string | null;
  role: "user" | "assistant" | "tool" | "system";
  content: MessageContent | null;
  tool_calls?: Record<string, unknown>[];
  created_at: string;
}

export interface Session {
  id: string;
  title: string;
  status: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  message_count: number;
}
