import { useState } from "react";
import { Box, Typography, Tabs, Tab, Card, CardContent, TextField, Button, Switch, FormControlLabel, Select, MenuItem } from "@mui/material";
import { useThemeStore } from "../stores/theme-store";

export default function SettingsPage() {
  const { mode, setMode } = useThemeStore();
  const [tab, setTab] = useState(0);

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>Settings</Typography>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 3 }}>
        <Tab label="Profile" />
        <Tab label="Preferences" />
        <Tab label="Notifications" />
      </Tabs>

      {tab === 0 && (
        <Card>
          <CardContent>
            <TextField fullWidth label="Email" size="small" sx={{ mb: 2 }} />
            <Button variant="contained">Save Changes</Button>
          </CardContent>
        </Card>
      )}

      {tab === 1 && (
        <Card>
          <CardContent>
            <Typography variant="subtitle2" gutterBottom>Theme</Typography>
            <Select value={mode} onChange={(e) => setMode(e.target.value as any)} size="small" sx={{ mb: 2, minWidth: 150 }}>
              <MenuItem value="light">Light</MenuItem>
              <MenuItem value="dark">Dark</MenuItem>
              <MenuItem value="system">System</MenuItem>
            </Select>
          </CardContent>
        </Card>
      )}

      {tab === 2 && (
        <Card>
          <CardContent>
            <FormControlLabel control={<Switch defaultChecked />} label="Email notifications" sx={{ mb: 1 }} />
            <FormControlLabel control={<Switch defaultChecked />} label="Browser push notifications" />
          </CardContent>
        </Card>
      )}
    </Box>
  );
}
