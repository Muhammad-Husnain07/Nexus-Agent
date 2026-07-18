import { useState } from "react"
import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import Card from "@mui/material/Card"
import Collapse from "@mui/material/Collapse"
import IconButton from "@mui/material/IconButton"
import ExpandMoreIcon from "@mui/icons-material/ExpandMore"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import type { ChatMessage } from "@/lib/types"

interface MessageBubbleProps {
  message: ChatMessage
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user"
  const isTool = message.role === "tool"
  const isSystem = message.role === "system"
  const hasToolCalls = message.tool_calls && message.tool_calls.length > 0

  if (isSystem) {
    return (
      <Box sx={{ textAlign: "center", py: 1 }}>
        <Typography variant="caption" color="text.secondary" sx={{ fontStyle: "italic" }}>{message.content}</Typography>
      </Box>
    )
  }

  return (
    <Box sx={{ display: "flex", justifyContent: isUser ? "flex-end" : "flex-start" }}>
      <Box sx={{
        maxWidth: "80%",
        borderRadius: 2,
        px: 2,
        py: 1,
        bgcolor: isUser ? "primary.main" : isTool ? "grey.100" : "grey.100",
        color: isUser ? "common.white" : "text.primary",
        fontFamily: isTool ? "monospace" : "inherit",
      }}>
        {message.content && (
          <Box sx={{ "& p:first-of-type": { mt: 0 }, "& p:last-of-type": { mb: 0 } }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
          </Box>
        )}
        {hasToolCalls && (
          <Box sx={{ mt: 1, display: "flex", flexDirection: "column", gap: 1 }}>
            {message.tool_calls!.map((tc) => (
              <ToolCallCard key={tc.id} toolCall={tc} />
            ))}
          </Box>
        )}
      </Box>
    </Box>
  )
}

function ToolCallCard({ toolCall }: { toolCall: NonNullable<ChatMessage["tool_calls"]>[number] }) {
  const [open, setOpen] = useState(true)
  const isRunning = toolCall.status === "running"

  return (
    <Card variant="outlined" sx={{ bgcolor: "background.default" }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, px: 1.5, py: 0.75 }}>
        {isRunning ? (
          <Box sx={{ display: "inline-block", width: 14, height: 14, border: 2, borderColor: "info.main", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.6s linear infinite" }} />
        ) : toolCall.status === "success" ? (
          <Typography variant="caption" color="success.main" sx={{ fontWeight: 700 }}>✓</Typography>
        ) : (
          <Typography variant="caption" color="error.main" sx={{ fontWeight: 700 }}>✗</Typography>
        )}
        <Typography variant="body2" sx={{ fontFamily: "monospace", fontWeight: 500 }}>{toolCall.tool_name}</Typography>
        <Box sx={{ flex: 1 }} />
        <IconButton size="small" onClick={() => setOpen(!open)} aria-label="toggle details">
          <ExpandMoreIcon sx={{ transform: open ? "rotate(180deg)" : "none", transition: "0.2s" }} />
        </IconButton>
      </Box>
      <Collapse in={open}>
        <Box sx={{ px: 1.5, pb: 1.5, display: "flex", flexDirection: "column", gap: 1 }}>
          <Box>
            <Typography variant="caption" color="text.secondary">Inputs:</Typography>
            <Box component="pre" sx={{ bgcolor: "grey.100", p: 1, borderRadius: 1, overflowX: "auto", typography: "caption" }}>
              {JSON.stringify(toolCall.inputs, null, 2)}
            </Box>
          </Box>
          {toolCall.outputs && (
            <Box>
              <Typography variant="caption" color="text.secondary">Outputs:</Typography>
              <Box component="pre" sx={{ bgcolor: "grey.100", p: 1, borderRadius: 1, overflowX: "auto", typography: "caption" }}>
                {JSON.stringify(toolCall.outputs, null, 2)}
              </Box>
            </Box>
          )}
          {toolCall.error && <Typography variant="caption" color="error.main">Error: {toolCall.error}</Typography>}
        </Box>
      </Collapse>
    </Card>
  )
}
