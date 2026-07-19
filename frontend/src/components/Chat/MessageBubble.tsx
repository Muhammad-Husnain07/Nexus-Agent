import { Box, Typography, Avatar, Paper, IconButton, Chip } from "@mui/material";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import PersonIcon from "@mui/icons-material/Person";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import ThumbUpIcon from "@mui/icons-material/ThumbUp";
import ThumbDownIcon from "@mui/icons-material/ThumbDown";

interface ToolCall { tool_name: string; status: string; }
interface Message { id: string; role: "user" | "assistant" | "tool" | "system"; content: string; tool_calls?: ToolCall[]; created_at: string; }
interface Props { message: Message; }

export default function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";
  const isTool = message.role === "tool";
  const isSystem = message.role === "system";

  if (isSystem) {
    return <Typography variant="caption" color="text.secondary" sx={{ textAlign: "center", display: "block", my: 1 }}>{message.content}</Typography>;
  }

  return (
    <Box display="flex" gap={1.5} mb={2} justifyContent={isUser ? "flex-end" : "flex-start"}>
      {!isUser && <Avatar sx={{ bgcolor: "primary.main", width: 32, height: 32 }}><SmartToyIcon fontSize="small" /></Avatar>}
      <Paper sx={{ p: 2, maxWidth: "70%", bgcolor: isUser ? "primary.main" : isTool ? "grey.100" : "background.paper", color: isUser ? "primary.contrastText" : "text.primary", borderRadius: 2 }}>
        <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>{message.content}</Typography>
        {message.tool_calls?.map((tc, i) => (
          <Chip key={i} label={`${tc.tool_name}: ${tc.status}`} size="small" color={tc.status === "success" ? "success" : "default"} sx={{ mt: 1, mr: 0.5 }} />
        ))}
        <Box display="flex" gap={0.5} mt={0.5}>
          <IconButton size="small"><ContentCopyIcon fontSize="small" /></IconButton>
          <IconButton size="small"><ThumbUpIcon fontSize="small" /></IconButton>
          <IconButton size="small"><ThumbDownIcon fontSize="small" /></IconButton>
        </Box>
      </Paper>
      {isUser && <Avatar sx={{ bgcolor: "secondary.main", width: 32, height: 32 }}><PersonIcon fontSize="small" /></Avatar>}
    </Box>
  );
}
