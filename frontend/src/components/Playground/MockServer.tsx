import { Box, Typography, Button, TextField, Chip, Switch, FormControlLabel } from "@mui/material";
import AddIcon from "@mui/icons-material/Add";

export default function MockServer() {
  return (
    <Box>
      <Box display="flex" justifyContent="space-between" mb={2}>
        <Typography variant="subtitle2">Mock Endpoints</Typography>
        <Button size="small" startIcon={<AddIcon />}>Add Endpoint</Button>
      </Box>
      <Box sx={{ p: 2, border: 1, borderColor: "divider", borderRadius: 1 }}>
        <Typography color="text.secondary" variant="body2">No mock endpoints defined.</Typography>
        <Typography color="text.secondary" variant="caption">Add mock responses to test agent behavior without real APIs.</Typography>
      </Box>
    </Box>
  );
}
