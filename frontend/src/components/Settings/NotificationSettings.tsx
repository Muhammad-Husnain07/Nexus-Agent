import { Box, Typography, Switch, FormControlLabel, FormGroup, Select, MenuItem, FormControl, InputLabel } from "@mui/material";

export default function NotificationSettings() {
  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom>Email Notifications</Typography>
      <FormGroup sx={{ mb: 2 }}>
        <FormControlLabel control={<Switch defaultChecked />} label="Approval requests" />
        <FormControlLabel control={<Switch defaultChecked />} label="Cost alerts" />
        <FormControlLabel control={<Switch />} label="System announcements" />
      </FormGroup>
      <Typography variant="subtitle2" gutterBottom>Quiet Hours</Typography>
      <FormControl size="small" sx={{ minWidth: 120, mr: 1 }}><InputLabel>From</InputLabel><Select label="From" defaultValue="22:00">
        <MenuItem value="22:00">10:00 PM</MenuItem><MenuItem value="23:00">11:00 PM</MenuItem></Select></FormControl>
      <FormControl size="small" sx={{ minWidth: 120 }}><InputLabel>To</InputLabel><Select label="To" defaultValue="07:00">
        <MenuItem value="07:00">7:00 AM</MenuItem><MenuItem value="08:00">8:00 AM</MenuItem></Select></FormControl>
    </Box>
  );
}
