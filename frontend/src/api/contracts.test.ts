import { describe, expect, it } from "vitest";

import {
  agentStateSchema,
  approvalPendingSchema,
  chatMessageSchema,
  parseContract,
  taskSchema,
} from "./contracts";

describe("runtime contract validation (G6 -> CI invariant)", () => {
  it("validates AgentStateResponse incl. approval_pending read model", () => {
    const state = parseContract(
      "AgentStateResponse",
      agentStateSchema,
      {
        session_id: "s1",
        status: "running",
        current_node: "ExecutorNode",
        final_response: null,
        approval_pending: {
          policy: "risky",
          step: "step_0",
          message: "Approve delete_users?",
          context: "This will perform: POST delete_users",
          tools: ["delete_users"],
          tool_details: {},
          requested_at: 1000,
          expires_at: 4600,
          expired: false,
        },
      },
    );
    expect(state.status).toBe("running");
    expect(state.approval_pending?.tools).toEqual(["delete_users"]);
    expect(state.approval_pending?.expired).toBe(false);
  });

  it("accepts a state without a pending approval", () => {
    const state = parseContract("AgentStateResponse", agentStateSchema, {
      session_id: "s1",
      status: "completed",
      current_node: null,
      final_response: "done",
      approval_pending: null,
    });
    expect(state.approval_pending).toBeNull();
  });

  it("rejects unknown run-status values (drift guard)", () => {
    expect(() =>
      parseContract("AgentStateResponse", agentStateSchema, {
        session_id: "s1",
        status: "in_progress", // not in the backend enum
        current_node: null,
        final_response: null,
        approval_pending: null,
      }),
    ).toThrow(/Contract mismatch/);
  });

  it("validates the approval expiry math contract", () => {
    const pending = approvalPendingSchema.safeParse({
      policy: "p",
      step: "s",
      message: "m",
      context: "c",
      tools: [],
      tool_details: {},
      requested_at: 1000,
      expires_at: 4600,
      expired: true,
    });
    expect(pending.success).toBe(true);
  });

  it("validates chat messages with dict content", () => {
    const msg = parseContract("ChatMessage", chatMessageSchema, {
      id: "m1",
      session_id: "s1",
      role: "assistant",
      content: { text: "hi", extra: 1 },
      created_at: "2026-01-01T00:00:00Z",
    });
    expect(msg.content?.text).toBe("hi");
  });

  it("rejects a chat message with string content (legacy drift guard)", () => {
    expect(() =>
      parseContract("ChatMessage", chatMessageSchema, {
        id: "m1",
        role: "assistant",
        content: "hi",
        created_at: "t",
      }),
    ).toThrow(/Contract mismatch/);
  });

  it("validates task statuses", () => {
    const task = parseContract("Task", taskSchema, {
      id: "t1",
      session_id: null,
      task_type: "workflow_run",
      status: "queued",
      payload: {},
      attempts: 0,
      max_attempts: 3,
      schedule_cron: null,
      next_run_at: null,
      error_message: null,
      started_at: null,
      completed_at: null,
      created_at: "2026-01-01T00:00:00Z",
    });
    expect(task.status).toBe("queued");
  });
});
