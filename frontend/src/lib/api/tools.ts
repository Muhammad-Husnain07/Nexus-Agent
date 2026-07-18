import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "./"
import type { ToolRead, ToolList, ToolCreate, ToolUpdate, ToolTestResponse } from "@/lib/types"
import type { AxiosResponse } from "axios"

interface GetToolsParams {
  page?: number
  page_size?: number
  enabled?: boolean
}

interface MutationContext {
  previous: ToolList | undefined
}

export function useGetTools(params?: GetToolsParams) {
  return useQuery<ToolList>({
    queryKey: ["tools", params],
    queryFn: () =>
      api.get<ToolList>("/tools", {
        params: { page: params?.page ?? 1, page_size: params?.page_size ?? 50, enabled: params?.enabled ?? true },
      }).then((r: AxiosResponse<ToolList>) => r.data),
  })
}

export function useGetTool(toolId: string | null) {
  return useQuery<ToolRead>({
    queryKey: ["tools", toolId],
    queryFn: () => api.get<ToolRead>(`/tools/${toolId}`).then((r: AxiosResponse<ToolRead>) => r.data),
    enabled: !!toolId,
  })
}

export function useCreateTool() {
  const queryClient = useQueryClient()

  return useMutation<ToolRead, Error, ToolCreate, MutationContext>({
    mutationFn: (data) => api.post<ToolRead>("/tools", data).then((r: AxiosResponse<ToolRead>) => r.data),
    onMutate: async (newTool) => {
      await queryClient.cancelQueries({ queryKey: ["tools"] })
      const key = ["tools", { page: 1, page_size: 50, enabled: true }]
      const previous = queryClient.getQueryData<ToolList>(key)
      if (previous) {
        const placeholder: ToolRead = {
          id: `temp-${Date.now()}`,
          tenant_id: "",
          name: newTool.name,
          description: newTool.description ?? "",
          purpose: newTool.purpose ?? "",
          endpoint_url: newTool.endpoint_url ?? "",
          http_method: newTool.http_method ?? "GET",
          auth_type: newTool.auth_type ?? "none",
          auth_ref: "",
          input_schema: newTool.input_schema ?? {},
          output_schema: newTool.output_schema ?? {},
          validation_rules: {},
          examples: [],
          tags: [],
          category: "general",
          requires_approval: newTool.requires_approval ?? false,
          risk_level: "low",
          enabled: newTool.enabled ?? true,
          tenant_public: false,
          idempotent: false,
          version: 1,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }
        queryClient.setQueryData<ToolList>(key, {
          ...previous,
          items: [placeholder, ...previous.items],
          total: previous.total + 1,
        })
      }
      return { previous }
    },
    onError: (_err, _newTool, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["tools", { page: 1, page_size: 50, enabled: true }], context.previous)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["tools"] })
    },
  })
}

export function useUpdateTool() {
  const queryClient = useQueryClient()

  return useMutation<ToolRead, Error, { id: string; data: ToolUpdate }, MutationContext>({
    mutationFn: ({ id, data }) => api.put<ToolRead>(`/tools/${id}`, data).then((r: AxiosResponse<ToolRead>) => r.data),
    onMutate: async ({ id, data }) => {
      await queryClient.cancelQueries({ queryKey: ["tools"] })
      const key = ["tools", { page: 1, page_size: 50, enabled: true }]
      const previous = queryClient.getQueryData<ToolList>(key)
      if (previous) {
        queryClient.setQueryData<ToolList>(key, {
          ...previous,
          items: previous.items.map((tool: ToolRead) =>
            tool.id === id ? { ...tool, ...data, updated_at: new Date().toISOString() } : tool,
          ),
        })
      }
      return { previous }
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["tools", { page: 1, page_size: 50, enabled: true }], context.previous)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["tools"] })
    },
  })
}

export function useDeleteTool() {
  const queryClient = useQueryClient()

  return useMutation<void, Error, string, MutationContext>({
    mutationFn: (id) => api.delete(`/tools/${id}`),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: ["tools"] })
      const key = ["tools", { page: 1, page_size: 50, enabled: true }]
      const previous = queryClient.getQueryData<ToolList>(key)
      if (previous) {
        queryClient.setQueryData<ToolList>(key, {
          ...previous,
          items: previous.items.filter((tool: ToolRead) => tool.id !== id),
          total: previous.total - 1,
        })
      }
      return { previous }
    },
    onError: (_err, _id, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["tools", { page: 1, page_size: 50, enabled: true }], context.previous)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["tools"] })
    },
  })
}

export function useTestTool() {
  return useMutation<ToolTestResponse, Error, { id: string; sampleInput: Record<string, unknown> }>({
    mutationFn: ({ id, sampleInput }) =>
      api.post<ToolTestResponse>(`/tools/${id}/test`, sampleInput).then((r: AxiosResponse<ToolTestResponse>) => r.data),
  })
}
