import { Box, TextField, IconButton, Typography, Avatar, Paper, Chip, CircularProgress, } from "@mui/material";
import SendIcon from "@mui/icons-material/Send";
import StopIcon from "@mui/icons-material/Stop";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import PersonIcon from "@mui/icons-material/Person";
import { useState } from "react";

interface Message {
  id: string;
  role: "user" | "assistant" | "tool";
  content: string;
}

export default function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const sendMessage = async () => {
    if (!input.trim()) return;
    const userMsg: Message = { id: crypto.randomUUID(), role: "user", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    setTimeout(() => {
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: "assistant", content: "This is a placeholder response." },
      ]);
      setLoading(false);
    }, 1000);
  };

  return (
    <Box display="flex" flexDirection="column" height="calc(100vh - 180px)">
      <Box flex={1} sx={{ overflowY: "auto", p: 2 }}>
        {messages.map((msg) => (
          <Box
            key={msg.id}
            display="flex"
            gap={1.5}
            mb={2}
            justifyContent={msg.role === "user" ? "flex-end" : "flex-start"}
          >
            {msg.role !== "user" && (
              <Avatar sx={{ bgcolor: "primary.main", width: 32, height: 32 }}>
                <SmartToyIcon fontSize="small" />
              </Avatar>
            )}
            <Paper
              sx={{
                p: 2,
                maxWidth: "70%",
                bgcolor: msg.role === "user" ? "primary.main" : "background.paper",
                color: msg.role === "user" ? "primary.contrastText" : "text.primary",
                borderRadius: 2,
              }}
            >
              <Typography variant="body2">{msg.content}</Typography>
            </Paper>
            {msg.role === "user" && (
              <Avatar sx={{ bgcolor: "secondary.main", width: 32, height: 32 }}>
                <PersonIcon fontSize="small" />
              </Avatar>
            )}
          </Box>
        ))}
        {loading && (
          <Box display="flex" justifyContent="center" py={2}>
            <CircularProgress size={24} />
          </Box>
        )}
      </Box>

      <Box display="flex" gap={1} p={2} sx={{ borderTop: 1, borderColor: "divider" }}>
        <TextField
          fullWidth
          size="small"
          placeholder="Type a message..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), sendMessage())}
          multiline
          maxRows={4}
        />
        <IconButton
          color="primary"
          onClick={loading ? () => {} : sendMessage}
          sx={{ alignSelf: "flex-end" }}
        >
          {loading ? <StopIcon /> : <SendIcon />}
        </IconButton>
      </Box>
    </Box>
  );
}
