import { useState } from "react";
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField, Select, MenuItem, FormControl, InputLabel } from "@mui/material";

interface Props { open: boolean; onClose: () => void; onSubmit: (data: { email: string; role: string }) => void; }

export default function UserForm({ open, onClose, onSubmit }: Props) {
  const [email, setEmail] = useState(""); const [role, setRole] = useState("developer");
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create User</DialogTitle>
      <DialogContent><TextField fullWidth label="Email" value={email} onChange={(e) => setEmail(e.target.value)} sx={{ mb: 2, mt: 1 }} />
        <FormControl fullWidth><InputLabel>Role</InputLabel><Select value={role} label="Role" onChange={(e) => setRole(e.target.value)}>
          <MenuItem value="developer">Developer</MenuItem><MenuItem value="end_user">End User</MenuItem><MenuItem value="viewer">Viewer</MenuItem>
          <MenuItem value="tenant_admin">Tenant Admin</MenuItem></Select></FormControl></DialogContent>
      <DialogActions><Button onClick={onClose}>Cancel</Button><Button variant="contained" onClick={() => { onSubmit({ email, role }); onClose(); }}>Create</Button></DialogActions>
    </Dialog>
  );
}
