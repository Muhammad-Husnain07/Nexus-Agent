import { Box, Typography, Dialog, DialogTitle, DialogContent, DialogActions, Button } from "@mui/material";
import { DataTable } from "../components/UI/DataTable";
import type { GridColDef } from "@mui/x-data-grid";
import { useState } from "react";

const columns: GridColDef[] = [
  { field: "id", headerName: "Run ID", width: 200 },
  { field: "session_id", headerName: "Session", width: 200 },
  { field: "status", headerName: "Status", width: 120 },
  { field: "model", headerName: "Model", width: 150 },
  { field: "created_at", headerName: "Started", width: 180 },
];

export default function AgentRunsPage() {
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null);
  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>Agent Runs</Typography>
      <DataTable columns={columns} rows={[]} emptyMessage="No agent runs" onPageChange={() => {}} />
      <Dialog open={!!selected} onClose={() => setSelected(null)} maxWidth="md" fullWidth>
        <DialogTitle>Run Details</DialogTitle>
        <DialogContent>{/* Timeline would go here */}</DialogContent>
        <DialogActions><Button onClick={() => setSelected(null)}>Close</Button></DialogActions>
      </Dialog>
    </Box>
  );
}
