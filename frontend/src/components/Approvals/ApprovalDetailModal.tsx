import { Dialog, DialogTitle, DialogContent, DialogActions, Button, Typography, Chip, TextField, Box, LinearProgress } from "@mui/material";

interface Props { open: boolean; onClose: () => void; approval: Record<string, unknown> | null; onDecide: (decision: string, comment?: string) => void; }

export default function ApprovalDetailModal({ open, onClose, approval, onDecide }: Props) {
  if (!approval) return null;
  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Approval Request</DialogTitle>
      <DialogContent>
        <Box mb={2}><Typography variant="subtitle2">Tool</Typography><Chip label={approval.tool_name as string} /></Box>
        <Box mb={2}><Typography variant="subtitle2">Risk Level</Typography><Chip label={approval.risk_level as string} color={(approval.risk_level as string) === "high" ? "error" : "warning"} /></Box>
        <Box mb={2}><Typography variant="subtitle2">Input</Typography><pre>{JSON.stringify(approval.inputs, null, 2)}</pre></Box>
        <TextField fullWidth multiline rows={3} label="Comment (optional)" size="small" />
        <Box mt={2}><LinearProgress variant="determinate" value={75} /><Typography variant="caption">Auto-reject in 5 minutes</Typography></Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button color="error" onClick={() => onDecide("reject")}>Reject</Button>
        <Button color="success" variant="contained" onClick={() => onDecide("approve")}>Approve</Button>
      </DialogActions>
    </Dialog>
  );
}
