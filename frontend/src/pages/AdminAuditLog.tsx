import { Box, Typography, Button } from "@mui/material";
import { DataTable } from "../components/UI/DataTable";
import type { GridColDef } from "@mui/x-data-grid";

const columns: GridColDef[] = [
  { field: "action", headerName: "Action", flex: 1 },
  { field: "resource_type", headerName: "Resource", width: 120 },
  { field: "actor_id", headerName: "Actor", width: 200 },
  { field: "created_at", headerName: "Timestamp", width: 180 },
];

export default function AdminAuditLogPage() {
  return (
    <Box>
      <Box display="flex" justifyContent="space-between" mb={3}>
        <Typography variant="h4" fontWeight={700}>Audit Log</Typography>
        <Button>Export</Button>
      </Box>
      <DataTable columns={columns} rows={[]} emptyMessage="No audit log entries" />
    </Box>
  );
}
