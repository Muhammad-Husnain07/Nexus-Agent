import { useState } from "react";
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, RadioGroup, FormControlLabel, Radio, Checkbox, FormGroup, FormControl, TextField } from "@mui/material";

interface Props { open: boolean; onClose: () => void; sessionTitle?: string; }

export default function ExportChatModal({ open, onClose, sessionTitle }: Props) {
  const [format, setFormat] = useState("json");
  const [includeTools, setIncludeTools] = useState(true);
  const [includeMeta, setIncludeMeta] = useState(true);

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Export Chat</DialogTitle>
      <DialogContent>
        <FormControl component="fieldset" sx={{ mb: 2 }}>
          <RadioGroup value={format} onChange={(e) => setFormat(e.target.value)}>
            <FormControlLabel value="json" control={<Radio />} label="JSON" />
            <FormControlLabel value="markdown" control={<Radio />} label="Markdown" />
            <FormControlLabel value="pdf" control={<Radio />} label="PDF" />
          </RadioGroup>
        </FormControl>
        <FormGroup sx={{ mb: 2 }}>
          <FormControlLabel control={<Checkbox checked={includeTools} onChange={(_, v) => setIncludeTools(v)} />} label="Include tool calls" />
          <FormControlLabel control={<Checkbox checked={includeMeta} onChange={(_, v) => setIncludeMeta(v)} />} label="Include metadata" />
        </FormGroup>
        <TextField fullWidth label="Share link (read-only)" size="small" value="" placeholder="Generate a share link..." />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={onClose}>Export</Button>
      </DialogActions>
    </Dialog>
  );
}
