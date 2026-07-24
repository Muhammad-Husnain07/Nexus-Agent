import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";
import type { Session } from "../types/session";
import type { PaginatedResponse } from "../types/common";

export function useSessionsList(params?: Record<string, unknown>) {
  return useQuery({
    queryKey: ["sessions-list", params],
    queryFn: async () => {
      const r = await api.get<PaginatedResponse<Session>>("/sessions", { params });
      return r.data;
    },
  });
}

export function useSessionDetail(id: string) {
  return useQuery({
    queryKey: ["session-detail", id],
    queryFn: async () => {
      const r = await api.get<Session>(`/sessions/${id}`);
      return r.data;
    },
    enabled: !!id,
  });
}

export function useCreateSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data?: { title?: string }) => {
      const r = await api.post<Session>("/sessions", data || {});
      return r.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sessions-list"] });
      qc.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}

export function useUpdateSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...data }: { id: string; title?: string; status?: string }) => {
      await api.patch(`/sessions/${id}`, data);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sessions-list"] });
      qc.invalidateQueries({ queryKey: ["session-detail"] });
      qc.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}

export function useArchiveSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/sessions/${id}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sessions-list"] });
      qc.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}

export function useForkSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, messageId }: { id: string; messageId: string }) => {
      const r = await api.post(`/sessions/${id}/fork`, { message_id: messageId });
      return r.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sessions-list"] });
      qc.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}

export function useMessages(sessionId: string, params?: Record<string, unknown>) {
  return useQuery({
    queryKey: ["messages", sessionId, params],
    queryFn: async () => {
      const r = await api.get<PaginatedResponse<{ id: string; role: string; content: string; created_at: string }>>(
        `/sessions/${sessionId}/messages`,
        { params }
      );
      return r.data;
    },
    enabled: !!sessionId,
  });
}
