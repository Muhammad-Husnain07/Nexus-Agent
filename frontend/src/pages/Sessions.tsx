import { Box, Typography } from "@mui/material";
import { DataTable } from "../components/UI/DataTable";
import type { GridColDef } from "@mui/x-data-grid";

const columns: GridColDef[] = [
  { field: "title", headerName: "Title", flex: 1 },
  { field: "status", headerName: "Status", width: 100 },
  { field: "message_count", headerName: "Messages", width: 100 },
  { field: "created_at", headerName: "Created", width: 180 },
];

export default function SessionsPage() {
  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>Sessions</Typography>
      <DataTable columns={columns} rows={[]} emptyMessage="No sessions yet" />
    </Box>
  );
}
