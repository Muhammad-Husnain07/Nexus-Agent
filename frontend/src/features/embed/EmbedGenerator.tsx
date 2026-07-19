import { Box, Typography, Card, CardContent, TextField, Button, Select, MenuItem, FormControl, InputLabel, Slider, Switch, FormControlLabel, } from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import PreviewIcon from "@mui/icons-material/Preview";

export default function EmbedGeneratorPage() {
  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>Embed Widget</Typography>
      <Card>
        <CardContent>
          <Typography variant="h6" gutterBottom>Widget Configuration</Typography>
          <Box display="flex" flexDirection="column" gap={2}>
            <TextField fullWidth label="Widget Title" size="small" />
            <FormControl fullWidth size="small">
              <InputLabel>Theme</InputLabel>
              <Select label="Theme" defaultValue="light">
                <MenuItem value="light">Light</MenuItem>
                <MenuItem value="dark">Dark</MenuItem>
                <MenuItem value="auto">Auto</MenuItem>
              </Select>
            </FormControl>
            <Box>
              <Typography variant="body2" gutterBottom>Border Radius</Typography>
              <Slider defaultValue={8} min={0} max={24} />
            </Box>
            <FormControlLabel control={<Switch />} label="Show Header" />
            <Box display="flex" gap={2}>
              <Button variant="contained" startIcon={<PreviewIcon />}>Preview</Button>
              <Button variant="outlined" startIcon={<CopyIcon />}>Copy Code</Button>
            </Box>
          </Box>
        </CardContent>
      </Card>
    </Box>
  );
}
