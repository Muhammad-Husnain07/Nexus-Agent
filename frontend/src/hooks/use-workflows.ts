import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createWorkflow,
  deleteWorkflow,
  getWorkflow,
  listWorkflowInstances,
  listWorkflows,
  toggleWorkflow,
  updateWorkflow,
  type WorkflowInput,
} from "../api/workflows";

export function useWorkflows(enabled?: boolean) {
  return useQuery({ queryKey: ["workflows", { enabled }], queryFn: () => listWorkflows(enabled) });
}

export function useWorkflow(id: string | null) {
  return useQuery({
    queryKey: ["workflows", "detail", id],
    queryFn: () => getWorkflow(id!),
    enabled: !!id,
  });
}

export function useWorkflowInstances(id: string | null, status?: string) {
  return useQuery({
    queryKey: ["workflows", "instances", id, status],
    queryFn: () => listWorkflowInstances(id!, { status }),
    enabled: !!id,
    refetchInterval: (query) => {
      const active = (query.state.data?.instances ?? []).some((instance) =>
        ["pending", "running", "paused"].includes(instance.status),
      );
      return active ? 5000 : false;
    },
  });
}

export function useCreateWorkflow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: WorkflowInput) => createWorkflow(input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workflows"] }),
  });
}

export function useUpdateWorkflow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: Partial<WorkflowInput> }) => updateWorkflow(id, input),
    onSuccess: (workflow) => {
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      queryClient.setQueryData(["workflows", "detail", workflow.id], workflow);
    },
  });
}

export function useDeleteWorkflow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteWorkflow(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workflows"] }),
  });
}

export function useToggleWorkflow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => toggleWorkflow(id, enabled),
    onSuccess: (workflow) => {
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      queryClient.setQueryData(["workflows", "detail", workflow.id], workflow);
    },
  });
}
