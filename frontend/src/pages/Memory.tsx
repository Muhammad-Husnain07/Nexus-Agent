import { useState } from "react";
import { Box, Typography, Tabs, Tab, TextField } from "@mui/material";
import { DataTable } from "../components/UI/DataTable";
import type { GridColDef } from "@mui/x-data-grid";

const columns: GridColDef[] = [
  { field: "content", headerName: "Content", flex: 1 },
  { field: "kind", headerName: "Kind", width: 120 },
  { field: "importance", headerName: "Importance", width: 100 },
  { field: "created_at", headerName: "Created", width: 180 },
];

export default function MemoryPage() {
  const [tab, setTab] = useState(0);

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>Memory</Typography>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Episodic" />
        <Tab label="Semantic" />
        <Tab label="Procedural" />
      </Tabs>
      <TextField size="small" placeholder="Search memories..." sx={{ mb: 2, maxWidth: 400 }} />
      <DataTable columns={columns} rows={[]} emptyMessage="No memories found" />
    </Box>
  );
}
