import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";

export function useMemories(params?: Record<string, unknown>) {
  return useQuery({ queryKey: ["memories", params], queryFn: async () => { const r = await api.get("/memory", { params }); return r.data; } });
}
export function useMemory(id: string) {
  return useQuery({ queryKey: ["memory", id], queryFn: async () => { const r = await api.get(`/memory/${id}`); return r.data; }, enabled: !!id });
}
export function useDeleteMemory() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: async (id: string) => { await api.delete(`/memory/${id}`); }, onSuccess: () => qc.invalidateQueries({ queryKey: ["memories"] }) });
}
export function useSearchMemories(query: string) {
  return useQuery({ queryKey: ["memories-search", query], queryFn: async () => { const r = await api.get("/memory", { params: { q: query } }); return r.data; }, enabled: query.length > 2 });
}
