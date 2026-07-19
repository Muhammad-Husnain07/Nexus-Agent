import { useEffect, useState, useCallback } from "react";
import { Box, TextField, IconButton, Typography, Paper, Avatar, CircularProgress } from "@mui/material";
import SendIcon from "@mui/icons-material/Send";
import SmartToyIcon from "@mui/icons-material/SmartToy";

export default function EmbeddedChatPage() {
  const params = new URLSearchParams(window.location.search);
  const widgetId = params.get("widget_id") || "default";
  const [messages, setMessages] = useState<{ role: string; content: string }[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const sendMessage = useCallback(async () => {
    if (!input.trim()) return;
    const userMsg = { role: "user", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    window.parent.postMessage({ type: "nexus:message", text: input }, "*");
    setTimeout(() => {
      setMessages((prev) => [...prev, { role: "assistant", content: "This is a placeholder response." }]);
      setLoading(false);
    }, 1000);
  }, [input]);

  useEffect(() => {
    const handler = (event: MessageEvent) => {
      if (event.data?.type === "nexus:config") {
        // Apply config from parent
      }
    };
    window.addEventListener("message", handler);
    window.parent.postMessage({ type: "nexus:ready", widgetId }, "*");
    return () => window.removeEventListener("message", handler);
  }, [widgetId]);

  return (
    <Box sx={{ height: "100vh", display: "flex", flexDirection: "column", bgcolor: "background.default" }}>
      <Box sx={{ p: 2, borderBottom: 1, borderColor: "divider", bgcolor: "primary.main", color: "primary.contrastText" }}>
        <Typography variant="subtitle1" fontWeight={600}>Nexus Assistant</Typography>
      </Box>
      <Box flex={1} sx={{ overflowY: "auto", p: 2 }}>
        {messages.map((msg, i) => (
          <Box key={i} display="flex" gap={1} mb={1.5} justifyContent={msg.role === "user" ? "flex-end" : "flex-start"}>
            {msg.role !== "user" && <Avatar sx={{ width: 28, height: 28, bgcolor: "primary.main" }}><SmartToyIcon sx={{ fontSize: 16 }} /></Avatar>}
            <Paper sx={{ p: 1.5, maxWidth: "80%", bgcolor: msg.role === "user" ? "primary.main" : "background.paper", color: msg.role === "user" ? "primary.contrastText" : "text.primary", borderRadius: 2 }}>
              <Typography variant="body2">{msg.content}</Typography>
            </Paper>
          </Box>
        ))}
        {loading && <Box textAlign="center" py={1}><CircularProgress size={20} /></Box>}
      </Box>
      <Box sx={{ p: 1.5, borderTop: 1, borderColor: "divider" }}>
        <TextField fullWidth size="small" placeholder="Type a message..." value={input} onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), sendMessage())}
          InputProps={{ endAdornment: <IconButton size="small" color="primary" onClick={sendMessage} disabled={!input.trim()}><SendIcon /></IconButton> }} />
      </Box>
    </Box>
  );
}
