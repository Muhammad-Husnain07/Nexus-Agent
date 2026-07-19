import { Card, CardContent, Typography, FormControl, InputLabel, Select, MenuItem, TextField, Switch, FormControlLabel, Button, Box, List, ListItem, ListItemText, Chip } from "@mui/material";

export default function AlertsConfig() {
  return (
    <Card><CardContent>
      <Typography variant="h6" gutterBottom>Alert Configuration</Typography>
      <Box display="flex" flexDirection="column" gap={2}>
        <FormControl size="small"><InputLabel>Alert Channel</InputLabel><Select label="Alert Channel" defaultValue="email">
          <MenuItem value="email">Email</MenuItem><MenuItem value="slack">Slack</MenuItem><MenuItem value="webhook">Webhook</MenuItem></Select></FormControl>
        <FormControlLabel control={<Switch defaultChecked />} label="Cost threshold exceeded" />
        <FormControlLabel control={<Switch />} label="Error rate spike" />
        <FormControlLabel control={<Switch defaultChecked />} label="Quota warning" />
        <Button variant="outlined" size="small">Save Alert Configuration</Button>
      </Box>
    </CardContent></Card>
  );
}
