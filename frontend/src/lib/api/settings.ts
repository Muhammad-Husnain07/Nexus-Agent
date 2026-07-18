import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "./"
import type { LlmProvider, TenantUpdate } from "@/lib/types"
import type { AxiosResponse } from "axios"

export function useGetTenant(tenantId: string | null | undefined) {
  return useQuery({
    queryKey: ["settings", "tenant", tenantId],
    queryFn: () => api.get(`/admin/tenants/${tenantId}`).then((r: AxiosResponse) => r.data),
    enabled: !!tenantId,
  })
}

export function useUpdateTenant() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ tenantId, data }: { tenantId: string; data: TenantUpdate }) =>
      api.patch(`/admin/tenants/${tenantId}`, data).then((r: AxiosResponse) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings", "tenant"] })
    },
  })
}

export function useUpdateUser() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ userId, data }: { userId: string; data: { role?: string; email?: string } }) =>
      api.patch(`/admin/users/${userId}`, data).then((r: AxiosResponse) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] })
    },
  })
}

export function useGetProviders() {
  return useQuery<LlmProvider[]>({
    queryKey: ["settings", "providers"],
    queryFn: async () => {
      // No backend endpoint yet — providers configured via env vars
      return []
    },
  })
}
