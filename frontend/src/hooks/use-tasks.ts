/**
 * Tasks hooks — TanStack Query owns task state (the ONLY authority);
 * Zustand holds no task state (FE Step 3 rule).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  actOnTask,
  createTask,
  getTask,
  isTaskActive,
  listTasks,
  taskListNeedsPolling,
  type TaskAction,
  type TaskFilters,
} from "../api/tasks";
import type { Task } from "../types/api";

const POLL_MS = 5000;

export function useTasks(filters: TaskFilters = {}, enabled = true) {
  return useQuery({
    queryKey: ["tasks", filters],
    queryFn: () => listTasks(filters),
    enabled,
    refetchInterval: (query) =>
      taskListNeedsPolling(query.state.data?.tasks) ? POLL_MS : false,
  });
}

export function useTask(taskId: string | null) {
  return useQuery({
    queryKey: ["tasks", "detail", taskId],
    queryFn: () => getTask(taskId!),
    enabled: !!taskId,
    refetchInterval: (query) =>
      query.state.data && isTaskActive(query.state.data.status) ? POLL_MS : false,
  });
}

export function useCreateTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createTask,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });
}

export function useTaskAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: TaskAction }) =>
      actOnTask(id, action),
    onSuccess: (updated: Task) => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["tasks", "detail", updated.id] });
    },
  });
}
