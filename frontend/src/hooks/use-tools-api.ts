import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";
import type { ToolDefinition, ToolCreatePayload } from "../types/tool";
import type { PaginatedResponse } from "../types/common";

export function useToolsList(params?: Record<string, unknown>) {
  return useQuery({
    queryKey: ["tools", params],
    queryFn: async () => {
      const res = await api.get<PaginatedResponse<ToolDefinition>>("/tools", { params });
      return res.data;
    },
  });
}

export function useTool(id: string) {
  return useQuery({
    queryKey: ["tool", id],
    queryFn: async () => {
      const res = await api.get<ToolDefinition>(`/tools/${id}`);
      return res.data;
    },
    enabled: !!id,
  });
}

export function useCreateTool() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: ToolCreatePayload) => {
      const res = await api.post<ToolDefinition>("/tools", data);
      return res.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tools"] }),
  });
}

export function useUpdateTool(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: Partial<ToolCreatePayload>) => {
      const res = await api.put<ToolDefinition>(`/tools/${id}`, data);
      return res.data;
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["tools"] }); qc.invalidateQueries({ queryKey: ["tool", id] }); },
  });
}

export function useDeleteTool() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => { await api.delete(`/tools/${id}`); },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tools"] }),
  });
}

export function useTestTool() {
  return useMutation({
    mutationFn: async ({ id, input }: { id: string; input: Record<string, unknown> }) => {
      const res = await api.post(`/tools/${id}/test`, input);
      return res.data;
    },
  });
}

export function useSearchTools(query: string, k = 10) {
  return useQuery({
    queryKey: ["tools-search", query, k],
    queryFn: async () => {
      const res = await api.get("/tools/search", { params: { q: query, k } });
      return res.data;
    },
    enabled: query.length > 2,
  });
}
