import { useState } from "react";
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField, Select, MenuItem, FormControl, InputLabel, Typography, IconButton, Box } from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";

interface Props { open: boolean; onClose: () => void; onSubmit: (data: { label: string; scopes?: string[] }) => void; onRevoke?: () => void; }

export default function ApiKeyModal({ open, onClose, onSubmit, onRevoke }: Props) {
  const [label, setLabel] = useState("");
  const [showKey, setShowKey] = useState<string | null>(null);
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{showKey ? "API Key Created" : "Create API Key"}</DialogTitle>
      <DialogContent>
        {showKey ? (
          <Box><Typography variant="body2" color="warning.main" gutterBottom>Copy this key now. You won't see it again.</Typography>
            <Box display="flex" gap={1} alignItems="center">
              <TextField fullWidth size="small" value={showKey} />
              <IconButton onClick={() => navigator.clipboard.writeText(showKey!)}><ContentCopyIcon /></IconButton>
            </Box>
          </Box>
        ) : (
          <><TextField fullWidth label="Label" value={label} onChange={(e) => setLabel(e.target.value)} sx={{ mb: 2, mt: 1 }} />
            <FormControl fullWidth><InputLabel>Scope</InputLabel><Select label="Scope" defaultValue="api">
              <MenuItem value="api">API Access</MenuItem><MenuItem value="embed">Embed Only</MenuItem></Select></FormControl></>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{showKey ? "Done" : "Cancel"}</Button>
        {!showKey && <Button variant="contained" onClick={() => { onSubmit({ label }); setShowKey("nex_" + Math.random().toString(36).slice(2)); }}>Create</Button>}
        {onRevoke && <Button color="error" onClick={onRevoke}>Revoke</Button>}
      </DialogActions>
    </Dialog>
  );
}
