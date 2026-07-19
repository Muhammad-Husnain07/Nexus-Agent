import { useState } from "react";
import { Card, CardContent, Typography, Switch, FormControlLabel, FormGroup, FormControl, FormLabel, Snackbar, Alert } from "@mui/material";

export default function ApprovalNotifications() {
  const [email, setEmail] = useState(true);
  const [browser, setBrowser] = useState(true);
  const [sound, setSound] = useState(false);
  return (
    <Card><CardContent>
      <Typography variant="h6" gutterBottom>Approval Notifications</Typography>
      <FormGroup>
        <FormControlLabel control={<Switch checked={email} onChange={(_, v) => setEmail(v)} />} label="Email notifications" />
        <FormControlLabel control={<Switch checked={browser} onChange={(_, v) => setBrowser(v)} />} label="Browser push notifications" />
        <FormControlLabel control={<Switch checked={sound} onChange={(_, v) => setSound(v)} />} label="Sound alert" />
      </FormGroup>
    </CardContent></Card>
  );
}
