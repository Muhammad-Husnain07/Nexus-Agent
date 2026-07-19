import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";

export function usePendingApprovals(sessionId?: string) {
  const path = sessionId ? `/approvals/pending/${sessionId}` : "/approvals/pending";
  return useQuery({ queryKey: ["approvals-pending", sessionId], queryFn: async () => { const r = await api.get(path); return r.data; } });
}
export function useApproval(id: string) {
  return useQuery({ queryKey: ["approval", id], queryFn: async () => { const r = await api.get(`/approvals/${id}`); return r.data; }, enabled: !!id });
}
export function useDecideApproval() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: async ({ id, decision, comment }: { id: string; decision: string; comment?: string }) => { await api.post(`/approvals/${id}/decide`, { decision, comment }); }, onSuccess: () => { qc.invalidateQueries({ queryKey: ["approvals"] }); } });
}
export function useApprovalStats() {
  return useQuery({ queryKey: ["approval-stats"], queryFn: async () => { const r = await api.get("/approvals/stats"); return r.data; } });
}
