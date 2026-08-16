/**
 * Tasks surface — typed + contract-validated at the boundary (FE Step 3).
 * TanStack Query is the AUTHORITATIVE task state; no component-level store.
 */
import { get, post } from "./client";
import { parseContract, taskSchema } from "./contracts";
import type { Task, TaskStatus } from "../types/api";

export interface TaskListResult {
  tasks: Task[];
  count: number;
}

export interface TaskFilters {
  status?: TaskStatus | string;
  task_type?: string;
  session_id?: string;
  limit?: number;
}

export async function listTasks(filters: TaskFilters = {}): Promise<TaskListResult> {
  const raw = await get<unknown>("/tasks", {
    status: filters.status || undefined,
    task_type: filters.task_type || undefined,
    session_id: filters.session_id || undefined,
    limit: filters.limit || undefined,
  });
  if (!raw || typeof raw !== "object" || !("tasks" in raw)) {
    throw new Error("Invalid tasks response");
  }
  const tasks = ((raw as { tasks: unknown[] }).tasks ?? []).map((t) =>
    parseContract("Task", taskSchema, t),
  );
  return { tasks, count: tasks.length };
}

export async function getTask(taskId: string): Promise<Task> {
  const raw = await get<unknown>(`/tasks/${taskId}`);
  return parseContract("Task", taskSchema, raw);
}

export async function createTask(body: {
  task_type: string;
  payload: Record<string, unknown>;
  session_id?: string | null;
  max_attempts?: number;
  schedule_cron?: string | null;
  next_run_at?: string | null;
}): Promise<Task> {
  const raw = await post<unknown>("/tasks", body);
  return parseContract("Task", taskSchema, raw);
}

export type TaskAction = "pause" | "resume" | "cancel";

export async function actOnTask(taskId: string, action: TaskAction): Promise<Task> {
  const raw = await post<unknown>(`/tasks/${taskId}/${action}`);
  return parseContract("Task", taskSchema, raw);
}

/** Terminal statuses — no polling needed once reached. */
export function isTaskActive(status: string | undefined | null): boolean {
  return status === "pending" || status === "queued" || status === "running";
}

/** Bounded polling: only poll while ANY task is still active. */
export function taskListNeedsPolling(tasks: Task[] | undefined): boolean {
  return (tasks ?? []).some((t) => isTaskActive(t.status));
}
