import { Dialog, DialogTitle, DialogContent, DialogActions, Button, List, ListItem, ListItemButton, ListItemText, TextField, Tabs, Tab, Box } from "@mui/material";
import { useState } from "react";

interface Props { open: boolean; onClose: () => void; onSelect: (secretId: string) => void; }

export default function SecretPickerModal({ open, onClose, onSelect }: Props) {
  const [tab, setTab] = useState(0);
  const [showNew, setShowNew] = useState(false);
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Select Credential</DialogTitle>
      <DialogContent>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}><Tab label="Existing" /><Tab label="Create New" /></Tabs>
        {tab === 0 ? (
          <List>
            <ListItem disablePadding><ListItemButton onClick={() => { onSelect("secret-1"); onClose(); }}>
              <ListItemText primary="Production API Key" secondary="sk-prod-***" /></ListItemButton></ListItem>
            <ListItem disablePadding><ListItemButton onClick={() => { onSelect("secret-2"); onClose(); }}>
              <ListItemText primary="Staging API Key" secondary="sk-staging-***" /></ListItemButton></ListItem>
          </List>
        ) : (
          <TextField fullWidth label="Secret Value" size="small" sx={{ mt: 1 }} />
        )}
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Cancel</Button></DialogActions>
    </Dialog>
  );
}
