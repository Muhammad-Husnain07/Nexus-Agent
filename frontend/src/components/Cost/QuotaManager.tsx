import { Card, CardContent, Typography, LinearProgress, Box, Button, Switch, FormControlLabel, TextField, Dialog, DialogTitle, DialogContent, DialogActions } from "@mui/material";
import { useState } from "react";

export default function QuotaManager() {
  const [open, setOpen] = useState(false);
  return (
    <Card><CardContent>
      <Typography variant="h6" gutterBottom>Usage Quotas</Typography>
      <Box mb={2}><Typography variant="caption">Monthly Spend</Typography><LinearProgress variant="determinate" value={45} color="warning" /><Typography variant="caption">$45 / $100</Typography></Box>
      <Box mb={2}><Typography variant="caption">Token Quota</Typography><LinearProgress variant="determinate" value={70} color="error" /><Typography variant="caption">700K / 1M</Typography></Box>
      <Box mb={2}><Typography variant="caption">Rate Limit</Typography><LinearProgress variant="determinate" value={30} /><Typography variant="caption">30 / 100 RPM</Typography></Box>
      <Button size="small" onClick={() => setOpen(true)}>Request Increase</Button>
      <Dialog open={open} onClose={() => setOpen(false)}><DialogTitle>Request Quota Increase</DialogTitle>
        <DialogContent><TextField fullWidth multiline rows={3} label="Reason" size="small" sx={{ mt: 1 }} /></DialogContent>
        <DialogActions><Button onClick={() => setOpen(false)}>Cancel</Button><Button variant="contained">Submit</Button></DialogActions></Dialog>
    </CardContent></Card>
  );
}
