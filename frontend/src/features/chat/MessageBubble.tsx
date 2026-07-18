import { useState } from "react"
import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import type { ChatMessage } from "@/lib/types"

interface MessageBubbleProps {
  message: ChatMessage
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user"
  const isTool = message.role === "tool"
  const isSystem = message.role === "system"
  const hasToolCalls = message.tool_calls && message.tool_calls.length > 0

  return (
    <Box sx={{ display: "flex", justifyContent: isUser ? "flex-end" : "flex-start" }}>
      <Box
        sx={{
          maxWidth: "80%",
          borderRadius: 2,
          px: 2,
          py: 1,
          typography: isTool ? "caption" : "body2",
          bgcolor: isUser ? "primary.main" : isTool ? "grey.100" : isSystem ? "grey.50" : "grey.100",
          color: isUser ? "common.white" : isTool || isSystem ? "text.secondary" : "text.primary",
          fontFamily: isTool ? "monospace" : "inherit",
          fontStyle: isSystem ? "italic" : "inherit",
        }}
      >
        {message.content && (
          <Box sx={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{message.content}</Box>
        )}

        {hasToolCalls && (
          <Box sx={{ mt: 1, display: "flex", flexDirection: "column", gap: 1, borderTop: 1, borderColor: "divider", pt: 1 }}>
            {message.tool_calls!.map((tc) => (
              <ToolCallBlock key={tc.id} toolCall={tc} />
            ))}
          </Box>
        )}
      </Box>
    </Box>
  )
}

function ToolCallBlock({ toolCall }: { toolCall: NonNullable<ChatMessage["tool_calls"]>[number] }) {
  const [open, setOpen] = useState(true)
  const isRunning = toolCall.status === "running"

  return (
    <Box
      component="details"
      open={open || isRunning}
      onToggle={(e: React.BaseSyntheticEvent) => setOpen(e.target.open)}
      sx={{
        typography: "caption",
        border: 1,
        borderColor: "divider",
        borderRadius: 1,
        overflow: "hidden",
        "& summary": {
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          gap: 1,
          px: 1,
          py: 0.5,
          fontWeight: 500,
          "&:hover": { bgcolor: "action.hover" },
        },
      }}
    >
      <Box component="summary">
        <Box sx={{ display: "flex", alignItems: "center", gap: 0.5, flex: 1 }}>
          {isRunning ? (
            <Box sx={{ display: "inline-block", width: 12, height: 12, border: 2, borderColor: "currentColor", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.6s linear infinite" }} />
          ) : toolCall.status === "success" ? (
            <Typography sx={{ color: "success.main", lineHeight: 1 }}>&#10003;</Typography>
          ) : (
            <Typography sx={{ color: "error.main", lineHeight: 1 }}>&#10007;</Typography>
          )}
          <Typography variant="caption" sx={{ fontFamily: "monospace" }}>{toolCall.tool_name}</Typography>
          {isRunning && <Typography variant="caption" color="text.secondary" sx={{ ml: "auto" }}>running...</Typography>}
        </Box>
      </Box>
      <Box sx={{ px: 1, pb: 1, display: "flex", flexDirection: "column", gap: 0.5 }}>
        <Box>
          <Typography variant="caption" color="text.secondary">Inputs:</Typography>
          <Box component="pre" sx={{ bgcolor: "background.default", p: 0.5, borderRadius: 0.5, overflowX: "auto", mt: 0.25, fontSize: "0.7rem" }}>
            {JSON.stringify(toolCall.inputs, null, 2)}
          </Box>
        </Box>
        {toolCall.outputs && (
          <Box>
            <Typography variant="caption" color="text.secondary">Outputs:</Typography>
            <Box component="pre" sx={{ bgcolor: "background.default", p: 0.5, borderRadius: 0.5, overflowX: "auto", mt: 0.25, fontSize: "0.7rem" }}>
              {JSON.stringify(toolCall.outputs, null, 2)}
            </Box>
          </Box>
        )}
        {toolCall.error && (
          <Typography variant="caption" sx={{ color: "error.main" }}>Error: {toolCall.error}</Typography>
        )}
      </Box>
    </Box>
  )
}
