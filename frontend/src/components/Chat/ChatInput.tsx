import { useState } from "react";
import { Box, TextField, IconButton, Typography } from "@mui/material";
import SendIcon from "@mui/icons-material/Send";
import StopIcon from "@mui/icons-material/Stop";
import AttachFileIcon from "@mui/icons-material/AttachFile";

interface Props { onSend: (msg: string) => void; onStop?: () => void; loading?: boolean; }

export default function ChatInput({ onSend, onStop, loading }: Props) {
  const [value, setValue] = useState("");
  const handleSend = () => { if (value.trim()) { onSend(value.trim()); setValue(""); } };

  return (
    <Box sx={{ p: 2, borderTop: 1, borderColor: "divider" }}>
      <Box display="flex" gap={1} alignItems="flex-end">
        <IconButton size="small"><AttachFileIcon /></IconButton>
        <TextField fullWidth size="small" placeholder="Type a message..." value={value} onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }} multiline maxRows={4} />
        {loading ? (
          <IconButton color="error" onClick={onStop}><StopIcon /></IconButton>
        ) : (
          <IconButton color="primary" onClick={handleSend} disabled={!value.trim()}><SendIcon /></IconButton>
        )}
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: "block", textAlign: "right" }}>
        Enter to send · Shift+Enter for newline
      </Typography>
    </Box>
  );
}
