export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "tool" | "system";
  content: Record<string, unknown> | null;
  tool_calls?: Record<string, unknown>[];
  created_at: string;
}
