import { useState } from "react";
import { DataGrid, type GridColDef } from "@mui/x-data-grid";
import { Box, Button, Dialog, DialogTitle, DialogContent, DialogActions, TextField, Select, MenuItem, FormControl, InputLabel, IconButton } from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";

const columns: GridColDef[] = [
  { field: "label", headerName: "Label", flex: 1 },
  { field: "scope", headerName: "Scope", width: 120 },
  { field: "created_at", headerName: "Created", width: 180 },
  { field: "last_used", headerName: "Last Used", width: 180 },
  { field: "actions", headerName: "", width: 80, sortable: false, renderCell: () => <IconButton size="small" color="error"><DeleteIcon fontSize="small" /></IconButton> },
];

export default function PersonalApiKeys() {
  const [open, setOpen] = useState(false);
  const [showKey, setShowKey] = useState<string | null>(null);
  return (
    <Box>
      <Box display="flex" justifyContent="space-between" mb={2}><Button size="small" startIcon={<AddIcon />} onClick={() => setOpen(true)}>Create API Key</Button></Box>
      <DataGrid rows={[]} columns={columns} autoHeight disableRowSelectionOnClick sx={{ "& .MuiDataGrid-cell": { py: 1 } }} />
      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{showKey ? "Key Created" : "Create API Key"}</DialogTitle>
        <DialogContent>
          {showKey ? <Box display="flex" gap={1}><TextField fullWidth size="small" value={showKey} /><IconButton onClick={() => navigator.clipboard.writeText(showKey!)}><ContentCopyIcon /></IconButton></Box>
          : <><TextField fullWidth label="Label" size="small" sx={{ mb: 2, mt: 1 }} />
            <FormControl fullWidth size="small"><InputLabel>Scope</InputLabel><Select label="Scope" defaultValue="api">
              <MenuItem value="api">API Access</MenuItem><MenuItem value="embed">Embed Only</MenuItem></Select></FormControl></>}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          {!showKey && <Button variant="contained" onClick={() => setShowKey("nex_" + Math.random().toString(36).slice(2))}>Create</Button>}
        </DialogActions>
      </Dialog>
    </Box>
  );
}
