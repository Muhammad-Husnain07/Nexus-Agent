/**
 * Runtime contract validation — backend responses are validated at the
 * client boundary BEFORE entering TanStack Query / Zustand state.
 *
 * Backend schema drift becomes a typed, testable failure instead of a
 * silent runtime misbehavior (FE plan G6 -> CI invariant).
 */
import { z } from "zod";

export const apiErrorBodySchema = z.object({
  error: z
    .object({
      code: z.string().optional(),
      message: z.string().optional(),
      request_id: z.string().optional(),
    })
    .optional(),
  detail: z.string().optional(),
  error_code: z.string().optional(),
});

export const approvalPendingSchema = z.object({
  policy: z.string(),
  step: z.string(),
  message: z.string(),
  context: z.string(),
  tools: z.array(z.string()),
  tool_details: z.record(z.string(), z.unknown()),
  requested_at: z.number().nullable(),
  expires_at: z.number().nullable(),
  expired: z.boolean(),
});

export const agentStateSchema = z.object({
  session_id: z.string(),
  status: z.enum([
    "running",
    "completed",
    "cancelled",
    "timed_out",
    "interrupted",
    "failed",
  ]),
  current_node: z.string().nullable(),
  final_response: z.string().nullable(),
  error: z.string().nullable().optional(),
  approval_pending: approvalPendingSchema.nullable(),
});

export const agentEventSchema = z.object({
  type: z.string(),
  ts: z.string(),
  payload: z.record(z.string(), z.unknown()),
});

export const chatResponseSchema = z.object({
  session_id: z.string(),
  final_response: z.string().nullable(),
  requires_approval: z.boolean(),
  approval_payload: z.record(z.string(), z.unknown()).nullable(),
  interrupted: z.boolean(),
  error: z.string().nullable(),
  events: z.array(agentEventSchema),
  request_id: z.string().nullable().optional(),
});

export const messageContentSchema = z
  .record(z.string(), z.unknown())
  .nullable();

export const chatMessageSchema = z.object({
  id: z.string(),
  session_id: z.string().optional(),
  parent_id: z.string().nullable().optional(),
  role: z.enum(["user", "assistant", "tool", "system"]),
  content: messageContentSchema,
  tool_calls: z.array(z.record(z.string(), z.unknown())).optional(),
  created_at: z.string(),
});

export const toolResultSchema = z.object({
  tool_id: z.string(),
  tool_name: z.string(),
  status: z.enum([
    "success",
    "error",
    "timeout",
    "validation_error",
    "interrupted",
  ]),
  http_status: z.number().nullable().optional(),
  data: z.unknown().nullable().optional(),
  error: z.string().nullable().optional(),
  duration_ms: z.number(),
  retried: z.boolean(),
  raw_response_excerpt: z.string().nullable().optional(),
  response_headers: z.record(z.string(), z.unknown()).nullable().optional(),
});

export const taskSchema = z.object({
  id: z.string(),
  session_id: z.string().nullable(),
  task_type: z.string(),
  status: z.enum([
    "pending",
    "queued",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
  ]),
  payload: z.record(z.string(), z.unknown()),
  result: z.unknown().nullable().optional(),
  progress: z.unknown().nullable().optional(),
  attempts: z.number(),
  max_attempts: z.number(),
  cancel_requested: z.boolean().optional(),
  schedule_cron: z.string().nullable(),
  last_run_at: z.string().nullable().optional(),
  next_run_at: z.string().nullable(),
  error_message: z.string().nullable(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
  created_at: z.string().nullable(),
  updated_at: z.string().nullable().optional(),
});

export const workflowInstanceSchema = z.object({
  id: z.string(),
  definition_id: z.string(),
  session_id: z.string().nullable(),
  status: z.string(),
  current_step: z.number().nullable(),
  collected: z.record(z.string(), z.unknown()),
  error_message: z.string().nullable(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
});

export const workflowStepSchema = z.object({
  id: z.string(),
  description: z.string().optional(),
  intent: z.string().nullable().optional(),
  capability: z.string().nullable().optional(),
  requires_input: z.boolean().optional(),
  question: z.string().nullable().optional(),
  inputs: z.record(z.string(), z.unknown()).optional(),
  dynamic: z.boolean().optional(),
  workflow_ref: z.string().nullable().optional(),
  template: z.string().nullable().optional(),
});

export const workflowSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),
  trigger_intent_pattern: z.string(),
  steps: z.array(workflowStepSchema),
  priority: z.number(),
  max_nodes: z.number(),
  enabled: z.boolean(),
  version: z.number(),
  created_at: z.string().nullable(),
  updated_at: z.string().nullable(),
});

export const memorySchema = z.object({
  id: z.string(),
  session_id: z.string().nullable(),
  kind: z.enum(["episodic", "semantic", "procedural"]),
  content: z.string(),
  metadata_: z.record(z.string(), z.unknown()).nullable(),
  importance: z.number(),
  created_at: z.string(),
  last_accessed_at: z.string().nullable(),
});

export class ContractError extends Error {
  constructor(
    public readonly contract: string,
    public readonly issues: z.ZodIssue[],
  ) {
    super(`Contract mismatch (${contract}): ${issues[0]?.message ?? "unknown"}`);
    this.name = "ContractError";
  }
}

/**
 * Validate an unknown payload against a zod schema and return the typed
 * value, or throw ContractError (fail loud — never let bad shapes into
 * state).
 */
export function parseContract<T>(contract: string, schema: z.ZodType<T>, raw: unknown): T {
  const result = schema.safeParse(raw);
  if (!result.success) {
    throw new ContractError(contract, result.error.issues);
  }
  return result.data;
}
