import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";

export function useTenants(params?: Record<string, unknown>) {
  return useQuery({ queryKey: ["tenants", params], queryFn: async () => { const r = await api.get("/admin/tenants", { params }); return r.data; } });
}
export function useTenant(id: string) {
  return useQuery({ queryKey: ["tenant", id], queryFn: async () => { const r = await api.get(`/admin/tenants/${id}`); return r.data; }, enabled: !!id });
}
export function useCreateTenant() {
  const qc = useQueryClient(); return useMutation({ mutationFn: async (data: { name: string; slug: string }) => { const r = await api.post("/admin/tenants", data); return r.data; }, onSuccess: () => qc.invalidateQueries({ queryKey: ["tenants"] }) });
}
export function useUpdateTenant() {
  const qc = useQueryClient(); return useMutation({ mutationFn: async ({ id, ...data }: { id: string; name?: string }) => { await api.patch(`/admin/tenants/${id}`, data); }, onSuccess: () => qc.invalidateQueries({ queryKey: ["tenants"] }) });
}
export function useAdminUsers(params?: Record<string, unknown>) {
  return useQuery({ queryKey: ["admin-users", params], queryFn: async () => { const r = await api.get("/admin/users", { params }); return r.data; } });
}
export function useCreateUser() {
  const qc = useQueryClient(); return useMutation({ mutationFn: async (data: { email: string; role: string }) => { const r = await api.post("/admin/users", data); return r.data; }, onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }) });
}
export function useApiKeys(tenantId?: string) {
  return useQuery({ queryKey: ["api-keys", tenantId], queryFn: async () => { const r = await api.get(`/admin/tenants/${tenantId}/api-keys`); return r.data; }, enabled: !!tenantId });
}
export function useCreateApiKey() {
  const qc = useQueryClient(); return useMutation({ mutationFn: async ({ tenantId, ...data }: { tenantId: string; label?: string }) => { const r = await api.post(`/admin/tenants/${tenantId}/api-keys`, data); return r.data; }, onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys"] }) });
}
export function useRevokeApiKey() {
  const qc = useQueryClient(); return useMutation({ mutationFn: async ({ tenantId, keyId }: { tenantId: string; keyId: string }) => { await api.delete(`/admin/tenants/${tenantId}/api-keys/${keyId}`); }, onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys"] }) });
}
export function useAuditLog(params?: Record<string, unknown>) {
  return useQuery({ queryKey: ["audit-log", params], queryFn: async () => { const r = await api.get("/admin/audit-log", { params }); return r.data; } });
}
