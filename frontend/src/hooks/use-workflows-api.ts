import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";
import type { Task, TaskList, Workflow, WorkflowList } from "../types/workflow";

// ---------------------------------------------------------------------------
// Workflows
// ---------------------------------------------------------------------------

export function useWorkflowsList(enabled?: boolean) {
  return useQuery({
    queryKey: ["workflows", enabled],
    queryFn: async () => {
      const res = await api.get<WorkflowList>("/workflows", {
        params: enabled === undefined ? {} : { enabled },
      });
      return res.data;
    },
  });
}

export function useCreateWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: Record<string, unknown>) => {
      const res = await api.post<Workflow>("/workflows", data);
      return res.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows"] }),
  });
}

export function useUpdateWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: Record<string, unknown> }) => {
      const res = await api.put<Workflow>(`/workflows/${id}`, data);
      return res.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows"] }),
  });
}

export function useDeleteWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/workflows/${id}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows"] }),
  });
}

export function useToggleWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, enabled }: { id: string; enabled: boolean }) => {
      const res = await api.post<Workflow>(`/workflows/${id}/${enabled ? "activate" : "deactivate"}`);
      return res.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workflows"] }),
  });
}

// ---------------------------------------------------------------------------
// Tasks
// ---------------------------------------------------------------------------

export function useTasksList(status?: string) {
  return useQuery({
    queryKey: ["tasks", status],
    queryFn: async () => {
      const res = await api.get<TaskList>("/tasks", {
        params: status ? { status } : {},
      });
      return res.data;
    },
    refetchInterval: 5000,
  });
}

export function useCreateTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: Record<string, unknown>) => {
      const res = await api.post<Task>("/tasks", data);
      return res.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });
}

export function useTaskAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, action }: { id: string; action: "pause" | "resume" | "cancel" }) => {
      const res = await api.post<Task>(`/tasks/${id}/${action}`);
      return res.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });
}
