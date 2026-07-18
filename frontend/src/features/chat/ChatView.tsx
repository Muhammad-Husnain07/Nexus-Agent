import { useEffect, useRef, useCallback } from "react"
import { useNavigate } from "react-router-dom"
import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import CircularProgress from "@mui/material/CircularProgress"
import Alert from "@mui/material/Alert"
import { useGetSession, useGetMessages } from "@/lib/api/sessions"
import { useCreateSession } from "@/lib/api/sessions"
import { streamChat } from "@/lib/api/chat"
import { useChatStore } from "./chatStore"
import MessageList from "./MessageList"
import ChatInput from "./ChatInput"
import type { ToolCallDisplay } from "@/lib/types"

interface ChatViewProps {
  sessionId: string | null
}

export default function ChatView({ sessionId }: ChatViewProps) {
  const navigate = useNavigate()
  const messages = useChatStore((s) => s.messages)
  const addMessage = useChatStore((s) => s.addMessage)
  const addToolCall = useChatStore((s) => s.addToolCall)
  const updateToolCall = useChatStore((s) => s.updateToolCall)
  const appendToLastAssistant = useChatStore((s) => s.appendToLastAssistant)
  const setStatus = useChatStore((s) => s.setStatus)
  const setError = useChatStore((s) => s.setError)
  const loadMessages = useChatStore((s) => s.loadMessages)
  const setApprovalData = useChatStore((s) => s.setApprovalData)
  const approvalData = useChatStore((s) => s.approvalData)

  const { data: session, isLoading: sessionLoading } = useGetSession(sessionId)
  const { data: persistedMessages, isLoading: messagesLoading } = useGetMessages(sessionId)
  const createSession = useCreateSession()

  const abortRef = useRef<AbortController | null>(null)
  const sessionResolved = useRef(sessionId)

  useEffect(() => {
    if (persistedMessages && persistedMessages.items.length > 0 && messages.length === 0) {
      const mapped = persistedMessages.items.map((m) => ({
        id: m.id,
        role: m.role as "user" | "assistant" | "tool" | "system",
        content: typeof m.content === "string" ? m.content : m.content ? JSON.stringify(m.content) : "",
        created_at: m.created_at,
      }))
      loadMessages(mapped)
    }
  }, [persistedMessages])

  useEffect(() => {
    if (sessionResolved.current !== sessionId) {
      sessionResolved.current = sessionId
      if (!persistedMessages || persistedMessages.items.length === 0) {
        useChatStore.getState().clearMessages()
      }
    }
  }, [sessionId])

  const handleSend = useCallback(
    async (text: string) => {
      let sid = sessionId
      if (!sid) {
        try {
          const newSession = await createSession.mutateAsync({ title: text.slice(0, 80) })
          sid = newSession.id
          navigate(`/chat/${sid}`, { replace: true })
        } catch (err) {
          setError(err instanceof Error ? err.message : "Failed to create session")
          return
        }
      }

      addMessage({ id: `user-${Date.now()}`, role: "user", content: text, created_at: new Date().toISOString() })
      const assistantId = `assistant-${Date.now()}`
      addMessage({ id: assistantId, role: "assistant", content: "", created_at: new Date().toISOString() })

      setStatus("thinking")
      const abortController = new AbortController()
      abortRef.current = abortController

      try {
        await streamChat(sid, text, {
          onPlanCreated: () => setStatus("executing_tool"),
          onToolCallStarted: (payload) => {
            const tc: ToolCallDisplay = {
              id: `tc-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
              tool_name: payload.tool_name,
              status: "running",
              inputs: payload.inputs,
            }
            addToolCall(tc)
          },
          onToolCallCompleted: (payload) => {
            const toolId = useChatStore.getState().activeToolCallId
            if (toolId) {
              updateToolCall(toolId, {
                status: payload.status === "success" ? "success" : "error",
                outputs: payload.data as Record<string, unknown> | undefined,
                error: payload.error,
              })
            }
            setStatus("thinking")
          },
          onClarificationNeeded: (payload) => {
            appendToLastAssistant(payload.question)
            setStatus("idle")
          },
          onIntermediatePreview: (payload) => appendToLastAssistant(payload.text + "\n"),
          onApprovalRequired: (payload) => {
            setApprovalData({
              approval_id: (payload.approval_id as string) || "",
              tool_name: (payload.tool_name as string) || "unknown",
              risk_level: (payload.risk_level as string) || "medium",
              inputs: (payload.inputs as Record<string, unknown>) || {},
              description: payload.description as string | undefined,
              session_id: payload.session_id as string | undefined,
            })
          },
          onFinalResponse: (payload) => {
            appendToLastAssistant(payload.text)
            setStatus("idle")
          },
          onError: (payload) => setError(payload.message),
          onDone: () => setStatus("idle"),
        }, abortController.signal)
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === "AbortError") {
          setStatus("idle")
        } else {
          setError(err instanceof Error ? err.message : "Stream failed")
        }
      } finally {
        abortRef.current = null
      }
    },
    [sessionId, navigate, createSession, addMessage, addToolCall, updateToolCall, appendToLastAssistant, setStatus, setError, setApprovalData],
  )

  const handleStop = useCallback(() => abortRef.current?.abort(), [])

  if (!sessionId) {
    return (
      <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
        <MessageList />
        <ChatInput onSend={handleSend} onStop={handleStop} />
      </Box>
    )
  }

  if (sessionLoading || messagesLoading) {
    return <Box sx={{ display: "flex", justifyContent: "center", py: 10 }}><CircularProgress /></Box>
  }

  if (!session) {
    return <Alert severity="error">Session not found</Alert>
  }

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Box sx={{ borderBottom: 1, borderColor: "divider", px: 3, py: 1.5, flexShrink: 0 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>{session.title}</Typography>
        <Typography variant="caption" color="text.secondary">
          {session.message_count} messages &middot; {session.status}
        </Typography>
      </Box>
      <MessageList />
      {status === "error" && !approvalData && (
        <Box sx={{ px: 2, pb: 1 }}>
          <Alert severity="error" onClose={() => setStatus("idle")}>
            {useChatStore.getState().errorMessage || "An error occurred"}
          </Alert>
        </Box>
      )}
      <ChatInput onSend={handleSend} onStop={handleStop} />
    </Box>
  )
}
