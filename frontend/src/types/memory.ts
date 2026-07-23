export type MemoryKind = "episodic" | "semantic" | "procedural"

export const MEMORY_KINDS: { value: MemoryKind; label: string }[] = [
  { value: "episodic", label: "Episodic" },
  { value: "semantic", label: "Semantic" },
  { value: "procedural", label: "Procedural" },
]

export interface Memory {
  id: string
  session_id: string | null
  kind: MemoryKind
  content: string
  metadata_: Record<string, unknown> | null
  importance: number
  created_at: string
  last_accessed_at: string | null
}
