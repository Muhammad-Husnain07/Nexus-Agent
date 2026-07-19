import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";
import type { Session, Message, ChatRequest, ChatResponse } from "../types/chat";
import type { PaginatedResponse } from "../types/common";

export function useSessions() {
  return useQuery({ queryKey: ["sessions"], queryFn: async () => { const r = await api.get<PaginatedResponse<Session>>("/sessions"); return r.data; } });
}
export function useSession(id: string) {
  return useQuery({ queryKey: ["session", id], queryFn: async () => { const r = await api.get<Session>(`/sessions/${id}`); return r.data; }, enabled: !!id });
}
export function useCreateSession() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: async (data?: { title?: string }) => { const r = await api.post<Session>("/sessions", data || {}); return r.data; }, onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }) });
}
export function useRenameSession() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: async ({ id, title }: { id: string; title: string }) => { await api.patch(`/sessions/${id}`, { title }); }, onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }) });
}
export function useArchiveSession() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: async (id: string) => { await api.delete(`/sessions/${id}`); }, onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }) });
}
export function useMessages(sessionId: string, params?: Record<string, unknown>) {
  return useQuery({ queryKey: ["messages", sessionId, params], queryFn: async () => { const r = await api.get<PaginatedResponse<Message>>(`/sessions/${sessionId}/messages`, { params }); return r.data; }, enabled: !!sessionId });
}
export function useSendMessage() {
  return useMutation({ mutationFn: async ({ sessionId, data }: { sessionId: string; data: ChatRequest }) => { const r = await api.post<ChatResponse>(`/sessions/${sessionId}/chat`, data); return r.data; } });
}
export function useCancelRun() {
  return useMutation({ mutationFn: async (sessionId: string) => { /* WS close handled client-side */ } });
}
