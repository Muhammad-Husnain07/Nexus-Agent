import { useRef, useCallback } from "react"
import Box from "@mui/material/Box"
import TextField from "@mui/material/TextField"
import IconButton from "@mui/material/IconButton"
import SendIcon from "@mui/icons-material/Send"
import AttachFileIcon from "@mui/icons-material/AttachFile"
import StopIcon from "@mui/icons-material/Stop"
import Typography from "@mui/material/Typography"
import { useChatStore } from "./chatStore"

interface ChatInputProps {
  onSend: (message: string) => void
  onStop: () => void
  disabled?: boolean
}

export default function ChatInput({ onSend, onStop, disabled }: ChatInputProps) {
  const status = useChatStore((s) => s.status)
  const textRef = useRef<HTMLTextAreaElement>(null)
  const isRunning = status !== "idle" && status !== "error"

  const handleSend = useCallback(() => {
    const el = textRef.current
    if (!el) return
    const value = el.value.trim()
    if (!value || isRunning || disabled) return
    el.value = ""
    el.style.height = "auto"
    onSend(value)
  }, [onSend, isRunning, disabled])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  if (status === "awaiting_approval") {
    return (
      <Box sx={{ borderTop: 1, borderColor: "divider", p: 2, bgcolor: "background.default" }}>
        <Box sx={{ display: "flex", alignItems: "center", gap: 1, maxWidth: 800, mx: "auto" }}>
          <Typography variant="body2" color="warning.main">⏳ Agent is awaiting approval...</Typography>
        </Box>
      </Box>
    )
  }

  return (
    <Box sx={{ borderTop: 1, borderColor: "divider", p: 2, bgcolor: "background.default" }}>
      <Box sx={{ display: "flex", alignItems: "flex-end", gap: 1, maxWidth: 800, mx: "auto" }}>
        <IconButton size="small" sx={{ mb: 0.5 }} aria-label="attach file"><AttachFileIcon /></IconButton>
        <TextField
          inputRef={textRef}
          multiline
          maxRows={6}
          placeholder="Type a message..."
          onKeyDown={handleKeyDown}
          disabled={isRunning || disabled}
          size="small"
          sx={{ flex: 1, "& textarea": { resize: "none" } }}
        />
        {isRunning ? (
          <IconButton color="error" onClick={onStop} aria-label="stop"><StopIcon /></IconButton>
        ) : (
          <IconButton color="primary" onClick={handleSend} disabled={disabled} aria-label="send"><SendIcon /></IconButton>
        )}
      </Box>
    </Box>
  )
}
