import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteMemory, getMemory, listMemories, type MemoryFilters } from "../api/memory";

export function useMemoryQuery(filters: MemoryFilters = {}) {
  return useQuery({
    queryKey: ["memories", filters],
    queryFn: () => listMemories(filters),
  });
}

export function useMemoryDetail(id: string | null) {
  return useQuery({
    queryKey: ["memory", id],
    queryFn: () => getMemory(id!),
    enabled: !!id,
  });
}

export function useDeleteMemoryMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteMemory(id),
    onSuccess: (_data, id) => {
      queryClient.removeQueries({ queryKey: ["memory", id] });
      queryClient.invalidateQueries({ queryKey: ["memories"] });
    },
  });
}
