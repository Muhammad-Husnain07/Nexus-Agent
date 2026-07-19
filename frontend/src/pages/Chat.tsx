import { Box, Typography } from "@mui/material";
import ChatIcon from "@mui/icons-material/Chat";

export default function ChatPage() {
  return (
    <Box
      display="flex"
      flexDirection="column"
      alignItems="center"
      justifyContent="center"
      minHeight="60vh"
      color="text.secondary"
    >
      <ChatIcon sx={{ fontSize: 64, mb: 2, opacity: 0.3 }} />
      <Typography variant="h5" gutterBottom>Select a session</Typography>
      <Typography variant="body2">Choose a conversation from the sidebar or start a new chat</Typography>
    </Box>
  );
}
