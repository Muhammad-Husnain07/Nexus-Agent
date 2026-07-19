import { Box, Typography } from "@mui/material";
import { DataTable } from "../components/UI/DataTable";
import type { GridColDef } from "@mui/x-data-grid";

const columns: GridColDef[] = [
  { field: "email", headerName: "Email", flex: 1 },
  { field: "role", headerName: "Role", width: 150 },
  { field: "created_at", headerName: "Created", width: 180 },
];

export default function AdminUsersPage() {
  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>Users</Typography>
      <DataTable columns={columns} rows={[]} emptyMessage="No users found" />
    </Box>
  );
}
