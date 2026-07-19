import { Box, Typography, Paper, ToggleButtonGroup, ToggleButton } from "@mui/material";
import PhoneIphoneIcon from "@mui/icons-material/PhoneIphone";
import DesktopWindowsIcon from "@mui/icons-material/DesktopWindows";
import { useState } from "react";

export default function WidgetPreview() {
  const [mode, setMode] = useState("desktop");
  return (
    <Paper sx={{ p: 2 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
        <Typography variant="subtitle2">Preview</Typography>
        <ToggleButtonGroup size="small" value={mode} exclusive onChange={(_, v) => v && setMode(v)}>
          <ToggleButton value="desktop"><DesktopWindowsIcon fontSize="small" /></ToggleButton>
          <ToggleButton value="mobile"><PhoneIphoneIcon fontSize="small" /></ToggleButton>
        </ToggleButtonGroup>
      </Box>
      <Box sx={{ border: 1, borderColor: "divider", borderRadius: 1, height: mode === "mobile" ? 400 : 300, bgcolor: "grey.100", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Typography color="text.secondary">Widget Preview</Typography>
      </Box>
    </Paper>
  );
}
