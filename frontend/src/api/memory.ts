/** Contract-validated memory API. */
import { del, get } from "./client";
import { memorySchema, parseContract } from "./contracts";
import type { Memory, MemoryKind } from "../types/memory";

export interface MemoryFilters {
  q?: string;
  kind?: MemoryKind;
}

export async function listMemories(filters: MemoryFilters = {}): Promise<Memory[]> {
  const raw = await get<unknown>("/memory", filters);
  if (!Array.isArray(raw)) throw new Error("Invalid memory response");
  return raw.map((item) => parseContract("Memory", memorySchema, item));
}

export async function getMemory(id: string): Promise<Memory> {
  return parseContract("Memory", memorySchema, await get<unknown>(`/memory/${id}`));
}

export async function deleteMemory(id: string): Promise<void> {
  await del(`/memory/${id}`);
}
