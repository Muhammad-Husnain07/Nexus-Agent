import { useRef, useCallback } from "react"
import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import TextField from "@mui/material/TextField"
import Button from "@mui/material/Button"
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

  const handleInput = useCallback(() => {
    const el = textRef.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleSend = () => {
    const el = textRef.current
    if (!el) return
    const value = el.value.trim()
    if (!value || isRunning || disabled) return
    el.value = ""
    el.style.height = "auto"
    onSend(value)
  }

  if (status === "awaiting_approval") {
    return (
      <Box sx={{ borderTop: 1, borderColor: "divider", p: 2, bgcolor: "background.default" }}>
        <Box sx={{ maxWidth: 800, mx: "auto" }}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1, bgcolor: "warning.light", color: "warning.dark", border: 1, borderColor: "warning.main", borderRadius: 1, px: 2, py: 1.5 }}>
            <Typography sx={{ fontSize: "1.25rem" }}>⏳</Typography>
            <Typography variant="body2">Agent is awaiting approval...</Typography>
          </Box>
        </Box>
      </Box>
    )
  }

  return (
    <Box sx={{ borderTop: 1, borderColor: "divider", p: 2, bgcolor: "background.default" }}>
      <Box sx={{ display: "flex", alignItems: "flex-end", gap: 1, maxWidth: 800, mx: "auto" }}>
        <TextField
          inputRef={textRef}
          multiline
          maxRows={8}
          placeholder="Type a message..."
          onInput={handleInput}
          onKeyDown={handleKeyDown}
          disabled={isRunning || disabled}
          size="small"
          sx={{ flex: 1, "& textarea": { resize: "none" } }}
          slotProps={{ htmlInput: { sx: { minHeight: 20 } as React.CSSProperties } }}
        />

        {isRunning ? (
          <Button variant="contained" color="error" onClick={onStop} sx={{ flexShrink: 0 }}>
            Stop
          </Button>
        ) : (
          <Button variant="contained" onClick={handleSend} disabled={disabled} sx={{ flexShrink: 0 }}>
            Send
          </Button>
        )}
      </Box>
    </Box>
  )
}
