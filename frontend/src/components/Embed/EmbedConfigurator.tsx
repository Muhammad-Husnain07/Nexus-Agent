import { Box, TextField, Select, MenuItem, FormControl, InputLabel, Slider, Switch, FormControlLabel, Button, Typography } from "@mui/material";

export default function EmbedConfigurator() {
  return (
    <Box display="flex" flexDirection="column" gap={2}>
      <TextField fullWidth size="small" label="Widget Title" />
      <FormControl fullWidth size="small"><InputLabel>Theme</InputLabel><Select label="Theme" defaultValue="light">
        <MenuItem value="light">Light</MenuItem><MenuItem value="dark">Dark</MenuItem><MenuItem value="auto">Auto</MenuItem></Select></FormControl>
      <Box><Typography variant="body2" gutterBottom>Border Radius</Typography><Slider defaultValue={8} min={0} max={24} /></Box>
      <FormControlLabel control={<Switch />} label="Show Header" />
      <FormControlLabel control={<Switch />} label="Animation" />
      <TextField fullWidth size="small" label="CORS Allowed Domains" placeholder="example.com" />
    </Box>
  );
}
