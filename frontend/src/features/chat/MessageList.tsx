import { useEffect, useRef } from "react"
import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import Skeleton from "@mui/material/Skeleton"
import { useChatStore } from "./chatStore"
import MessageBubble from "./MessageBubble"
import ApprovalCard from "./ApprovalCard"

export default function MessageList() {
  const messages = useChatStore((s) => s.messages)
  const status = useChatStore((s) => s.status)
  const approvalData = useChatStore((s) => s.approvalData)
  const clearApprovalData = useChatStore((s) => s.clearApprovalData)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages.length, status, approvalData])

  if (messages.length === 0 && !approvalData) {
    return (
      <Box sx={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "text.secondary" }}>
        <Box sx={{ textAlign: "center" }}>
          <Typography variant="h5" sx={{ fontWeight: 700, mb: 1 }}>Nexus Agent</Typography>
          <Typography variant="body2">Say hello to start the conversation.</Typography>
        </Box>
      </Box>
    )
  }

  return (
    <Box sx={{ flex: 1, overflowY: "auto", p: 2, display: "flex", flexDirection: "column", gap: 2 }}>
      {messages.map((msg) => <MessageBubble key={msg.id} message={msg} />)}
      {approvalData && <ApprovalCard data={approvalData} onDone={clearApprovalData} />}
      {status === "thinking" && (
        <Box sx={{ display: "flex", justifyContent: "flex-start", gap: 0.5 }}>
          {[0, 0.15, 0.3].map((delay) => (
            <Skeleton key={delay} variant="circular" width={8} height={8}
              sx={{ animation: "pulse 1s infinite", animationDelay: `${delay}s`, bgcolor: "text.disabled" }} />
          ))}
        </Box>
      )}
      <div ref={bottomRef} />
    </Box>
  )
}
