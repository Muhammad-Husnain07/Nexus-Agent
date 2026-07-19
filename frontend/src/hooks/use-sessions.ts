import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";
import type { Session } from "../types/session";
import type { PaginatedResponse } from "../types/common";

export function useSessionsList(params?: Record<string, unknown>) {
  return useQuery({ queryKey: ["sessions-list", params], queryFn: async () => { const r = await api.get<PaginatedResponse<Session>>("/sessions", { params }); return r.data; } });
}
export function useSessionDetail(id: string) {
  return useQuery({ queryKey: ["session-detail", id], queryFn: async () => { const r = await api.get<Session>(`/sessions/${id}`); return r.data; }, enabled: !!id });
}
export function useCreateSession() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: async () => { const r = await api.post<Session>("/sessions"); return r.data; }, onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }) });
}
export function useUpdateSession() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: async ({ id, ...data }: { id: string; title?: string; status?: string }) => { await api.patch(`/sessions/${id}`, data); }, onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }) });
}
export function useForkSession() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: async ({ id, messageId }: { id: string; messageId: string }) => { const r = await api.post(`/sessions/${id}/fork`, { message_id: messageId }); return r.data; }, onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }) });
}
