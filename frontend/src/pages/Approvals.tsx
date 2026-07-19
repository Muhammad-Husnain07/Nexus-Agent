import { useState } from "react";
import { Box, Typography, Tabs, Tab } from "@mui/material";
import { DataTable } from "../components/UI/DataTable";
import type { GridColDef } from "@mui/x-data-grid";

const columns: GridColDef[] = [
  { field: "tool_name", headerName: "Tool", flex: 1 },
  { field: "session_id", headerName: "Session", width: 200 },
  { field: "risk_level", headerName: "Risk Level", width: 120 },
  { field: "created_at", headerName: "Requested At", width: 180 },
  { field: "status", headerName: "Status", width: 120 },
];

export default function ApprovalsPage() {
  const [tab, setTab] = useState(0);

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>Approvals</Typography>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Pending" />
        <Tab label="History" />
      </Tabs>
      <DataTable columns={columns} rows={[]} emptyMessage="No pending approvals" />
    </Box>
  );
}
