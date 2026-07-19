import { Box, ToggleButtonGroup, ToggleButton, Select, MenuItem, FormControl, InputLabel, Slider, Typography, Paper } from "@mui/material";
import LightModeIcon from "@mui/icons-material/LightMode";
import DarkModeIcon from "@mui/icons-material/DarkMode";
import SettingsBrightnessIcon from "@mui/icons-material/SettingsBrightness";
import { useThemeStore } from "../../stores/theme-store";

export default function ThemeCustomizer() {
  const { mode, setMode } = useThemeStore();
  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom>Theme Mode</Typography>
      <ToggleButtonGroup exclusive value={mode} onChange={(_, v) => v && setMode(v)} sx={{ mb: 2 }}>
        <ToggleButton value="light"><LightModeIcon /></ToggleButton>
        <ToggleButton value="dark"><DarkModeIcon /></ToggleButton>
        <ToggleButton value="system"><SettingsBrightnessIcon /></ToggleButton>
      </ToggleButtonGroup>
      <Typography variant="subtitle2" gutterBottom>Density</Typography>
      <FormControl fullWidth size="small" sx={{ mb: 2 }}><Select defaultValue="comfortable">
        <MenuItem value="comfortable">Comfortable</MenuItem><MenuItem value="compact">Compact</MenuItem></Select></FormControl>
      <Typography variant="subtitle2" gutterBottom>Font Size</Typography>
      <Slider defaultValue={14} min={12} max={20} step={1} />
      <Paper sx={{ p: 2, mt: 2, bgcolor: "background.default" }}><Typography>Preview text</Typography></Paper>
    </Box>
  );
}
