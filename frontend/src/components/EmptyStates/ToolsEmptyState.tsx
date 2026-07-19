import { Box, Typography, Button, Link } from "@mui/material";
import BuildIcon from "@mui/icons-material/Build";
import { useNavigate } from "react-router-dom";

export default function ToolsEmptyState() {
  const navigate = useNavigate();
  return (
    <Box textAlign="center" py={8}>
      <BuildIcon sx={{ fontSize: 64, color: "text.secondary", mb: 2, opacity: 0.4 }} />
      <Typography variant="h6" gutterBottom>No Tools Yet</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3, maxWidth: 400, mx: "auto" }}>
        Tools are API endpoints that the agent can call. Register your first tool to get started.
      </Typography>
      <Button variant="contained" onClick={() => navigate("/tools/new")}>Create Your First Tool</Button>
      <Box mt={2}><Link href="#" underline="hover">Learn more about tools</Link></Box>
    </Box>
  );
}
