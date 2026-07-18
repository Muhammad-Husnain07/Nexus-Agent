import { create } from "zustand"
import type { ChatMessage, ToolCallDisplay, StreamStatus } from "@/lib/types"

export interface ApprovalData {
  approval_id: string
  tool_name: string
  risk_level: string
  inputs: Record<string, unknown>
  description?: string
  session_id?: string
}

interface ChatStore {
  messages: ChatMessage[]
  status: StreamStatus
  errorMessage: string | null
  activeToolCallId: string | null
  approvalData: ApprovalData | null

  addMessage: (msg: ChatMessage) => void
  updateLastMessage: (update: Partial<ChatMessage>) => void
  addToolCall: (toolCall: ToolCallDisplay) => void
  updateToolCall: (toolId: string, update: Partial<ToolCallDisplay>) => void
  appendToLastAssistant: (text: string) => void
  setStatus: (status: StreamStatus) => void
  setError: (msg: string) => void
  clearMessages: () => void
  loadMessages: (msgs: ChatMessage[]) => void
  setApprovalData: (data: ApprovalData) => void
  clearApprovalData: () => void
}

export const useChatStore = create<ChatStore>((set, get) => ({
  messages: [],
  status: "idle",
  errorMessage: null,
  activeToolCallId: null,
  approvalData: null,

  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),

  updateLastMessage: (update) =>
    set((s) => {
      if (s.messages.length === 0) return s
      const copy = [...s.messages]
      copy[copy.length - 1] = { ...copy[copy.length - 1], ...update }
      return { messages: copy }
    }),

  addToolCall: (toolCall) => {
    const state = get()
    const assistantIdx = state.messages.length - 1
    if (assistantIdx < 0) return
    set((s) => {
      const copy = [...s.messages]
      const msg = copy[assistantIdx]
      const tool_calls = [...(msg.tool_calls || []), toolCall]
      copy[assistantIdx] = { ...msg, tool_calls }
      return { messages: copy, activeToolCallId: toolCall.id, status: "executing_tool" }
    })
  },

  updateToolCall: (toolId, update) =>
    set((s) => {
      const assistantIdx = s.messages.length - 1
      if (assistantIdx < 0) return s
      const copy = [...s.messages]
      const msg = copy[assistantIdx]
      const tool_calls = (msg.tool_calls || []).map((tc) =>
        tc.id === toolId ? { ...tc, ...update } : tc,
      )
      copy[assistantIdx] = { ...msg, tool_calls }
      return { messages: copy, activeToolCallId: null }
    }),

  appendToLastAssistant: (text) =>
    set((s) => {
      if (s.messages.length === 0) return s
      const copy = [...s.messages]
      const last = copy[copy.length - 1]
      if (last.role !== "assistant") return s
      copy[copy.length - 1] = { ...last, content: last.content + text }
      return { messages: copy }
    }),

  setStatus: (status) => set({ status, errorMessage: status !== "error" ? null : undefined }),

  setError: (msg) => set({ status: "error", errorMessage: msg }),

  clearMessages: () => set({ messages: [], status: "idle", errorMessage: null, activeToolCallId: null, approvalData: null }),

  loadMessages: (msgs) => set({ messages: msgs, status: "idle" }),

  setApprovalData: (data) => set({ approvalData: data, status: "awaiting_approval" }),

  clearApprovalData: () => set({ approvalData: null, status: "idle" }),
}))
