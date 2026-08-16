/** Contract-validated workflow definitions and instances. */
import { del, get, patch, post, put } from "./client";
import { parseContract, workflowInstanceSchema, workflowSchema } from "./contracts";
import type { Workflow, WorkflowInstance, WorkflowStep } from "../types/workflow";

export interface WorkflowInput {
  name: string;
  description?: string;
  trigger_intent_pattern?: string;
  steps: WorkflowStep[];
  priority?: number;
  max_nodes?: number;
  enabled?: boolean;
}

export async function listWorkflows(enabled?: boolean): Promise<{ workflows: Workflow[]; count: number }> {
  const raw = await get<unknown>("/workflows", enabled === undefined ? undefined : { enabled });
  const value = raw as { workflows?: unknown[]; count?: number };
  const workflows = (value.workflows ?? []).map((item) => parseContract("Workflow", workflowSchema, item));
  return { workflows, count: Number(value.count ?? workflows.length) };
}

export async function getWorkflow(id: string): Promise<Workflow> {
  return parseContract("Workflow", workflowSchema, await get<unknown>(`/workflows/${id}`));
}

export async function createWorkflow(input: WorkflowInput): Promise<Workflow> {
  return parseContract("Workflow", workflowSchema, await post<unknown>("/workflows", input));
}

export async function updateWorkflow(id: string, input: Partial<WorkflowInput>): Promise<Workflow> {
  return parseContract("Workflow", workflowSchema, await put<unknown>(`/workflows/${id}`, input));
}

export async function deleteWorkflow(id: string): Promise<void> {
  await del(`/workflows/${id}`);
}

export async function toggleWorkflow(id: string, enabled: boolean): Promise<Workflow> {
  return parseContract(
    "Workflow",
    workflowSchema,
    await post<unknown>(`/workflows/${id}/${enabled ? "activate" : "deactivate"}`),
  );
}

export async function listWorkflowInstances(
  id: string,
  params?: { status?: string; limit?: number },
): Promise<{ instances: WorkflowInstance[]; count: number }> {
  const raw = await get<unknown>(`/workflows/${id}/instances`, params);
  const value = raw as { instances?: unknown[]; count?: number };
  const instances = (value.instances ?? []).map((item) =>
    parseContract("WorkflowInstance", workflowInstanceSchema, item),
  );
  return { instances, count: Number(value.count ?? instances.length) };
}
