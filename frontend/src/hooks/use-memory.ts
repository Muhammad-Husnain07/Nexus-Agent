import { useMemoryDetail, useMemoryQuery, useDeleteMemoryMutation } from "./use-memory-query";

export function useMemories(params: Record<string, unknown> = {}) {
  return useMemoryQuery({
    q: typeof params.q === "string" ? params.q : undefined,
    kind: params.kind === "episodic" || params.kind === "semantic" || params.kind === "procedural"
      ? params.kind
      : undefined,
  });
}

export function useMemory(id: string) {
  return useMemoryDetail(id);
}

export function useDeleteMemory() {
  return useDeleteMemoryMutation();
}

export function useSearchMemories(query: string) {
  return useMemoryQuery({ q: query.length > 2 ? query : undefined });
}
