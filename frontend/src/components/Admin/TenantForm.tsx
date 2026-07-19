import { useState } from "react";
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField } from "@mui/material";

interface Props { open: boolean; onClose: () => void; onSubmit: (data: { name: string; slug: string }) => void; }

export default function TenantForm({ open, onClose, onSubmit }: Props) {
  const [name, setName] = useState(""); const [slug, setSlug] = useState("");
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create Tenant</DialogTitle>
      <DialogContent><TextField fullWidth label="Name" value={name} onChange={(e) => setName(e.target.value)} sx={{ mb: 2, mt: 1 }} />
        <TextField fullWidth label="Slug" value={slug} onChange={(e) => setSlug(e.target.value)} /></DialogContent>
      <DialogActions><Button onClick={onClose}>Cancel</Button><Button variant="contained" onClick={() => { onSubmit({ name, slug }); onClose(); }}>Create</Button></DialogActions>
    </Dialog>
  );
}
