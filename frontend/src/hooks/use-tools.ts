import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import api from "@/lib/api"
import type { ToolDefinition, ToolCreatePayload, ToolUpdatePayload, ToolExecutionResult } from "@/types/tool"

export function useTools(params?: { tags?: string; category?: string; enabled?: boolean; page?: number; pageSize?: number }) {
  return useQuery({
    queryKey: ["tools", params],
    queryFn: async () => {
      const { data } = await api.get("/v1/tools", { params })
      return data as { items: ToolDefinition[]; total: number; page: number; page_size: number }
    },
  })
}

export function useTool(toolId: string | undefined) {
  return useQuery({
    queryKey: ["tools", toolId],
    queryFn: async () => {
      const { data } = await api.get(`/v1/tools/${toolId}`)
      return data as ToolDefinition
    },
    enabled: !!toolId,
  })
}

export function useCreateTool() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: ToolCreatePayload) => {
      const { data } = await api.post("/v1/tools", payload)
      return data as ToolDefinition
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tools"] }),
  })
}

export function useUpdateTool() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: ToolUpdatePayload & { id: string }) => {
      const { data } = await api.put(`/v1/tools/${id}`, payload)
      return data as ToolDefinition
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tools"] }),
  })
}

export function useDeleteTool() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/v1/tools/${id}`)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tools"] }),
  })
}

export function useTestTool() {
  return useMutation({
    mutationFn: async ({ toolId, inputs, dryRun }: { toolId: string; inputs?: Record<string, unknown>; dryRun?: boolean }) => {
      const { data } = await api.post(`/v1/tools/${toolId}/test`, inputs || {}, {
        params: { dry_run: dryRun ?? false },
      })
      return data as ToolExecutionResult
    },
  })
}
