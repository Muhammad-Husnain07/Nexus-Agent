import { useQuery } from "@tanstack/react-query";
import api from "../lib/api";

export function useCostSummary(days = 30, tenantId?: string) {
  return useQuery({ queryKey: ["cost-summary", days, tenantId], queryFn: async () => { const r = await api.get("/cost/summary", { params: { days, tenant_id: tenantId } }); return r.data; } });
}
export function useCostDaily(days = 30, tenantId?: string) {
  return useQuery({ queryKey: ["cost-daily", days, tenantId], queryFn: async () => { const r = await api.get("/cost/daily", { params: { days, tenant_id: tenantId } }); return r.data; } });
}
export function useCostByTenant(days = 30) {
  return useQuery({ queryKey: ["cost-by-tenant", days], queryFn: async () => { const r = await api.get("/cost/by-tenant", { params: { days } }); return r.data; } });
}
export function useAgentRuns(params?: Record<string, unknown>) {
  return useQuery({ queryKey: ["agent-runs", params], queryFn: async () => { const r = await api.get("/runs", { params }); return r.data; } });
}
