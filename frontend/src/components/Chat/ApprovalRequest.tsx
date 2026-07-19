import { Paper, Typography, Chip, Button, Box, TextField, LinearProgress } from "@mui/material";
import { useState } from "react";

interface Props {
  toolName: string;
  inputs: Record<string, unknown>;
  riskLevel: string;
  onApprove: () => void;
  onReject: (reason?: string) => void;
  onEdit?: () => void;
}

export default function ApprovalRequest({ toolName, inputs, riskLevel, onApprove, onReject, onEdit }: Props) {
  const [reason, setReason] = useState("");
  const [showReason, setShowReason] = useState(false);

  return (
    <Paper elevation={3} sx={{ p: 2, mb: 2, border: 1, borderColor: "warning.main", borderRadius: 2 }}>
      <Typography variant="subtitle2" gutterBottom color="warning.main">Approval Required</Typography>
      <Box mb={1}><Chip label={toolName} size="small" sx={{ mr: 1 }} /><Chip label={riskLevel} size="small" color={riskLevel === "high" ? "error" : "warning"} /></Box>
      <Typography variant="caption" color="text.secondary">Inputs:</Typography>
      <pre style={{ fontSize: 11, margin: "4px 0 8px" }}>{JSON.stringify(inputs, null, 2)}</pre>
      <LinearProgress variant="determinate" value={75} sx={{ mb: 1 }} />
      {showReason && <TextField fullWidth size="small" label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} sx={{ mb: 1 }} />}
      <Box display="flex" gap={1}>
        <Button size="small" color="success" variant="contained" onClick={onApprove}>Approve</Button>
        <Button size="small" color="error" onClick={() => setShowReason(true)}>Reject</Button>
        {showReason && <Button size="small" onClick={() => { onReject(reason); setShowReason(false); }}>Confirm</Button>}
        {onEdit && <Button size="small" onClick={onEdit}>Edit</Button>}
      </Box>
    </Paper>
  );
}
