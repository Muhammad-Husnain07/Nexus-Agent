import { Box, Typography } from "@mui/material";
import { DataTable } from "../components/UI/DataTable";
import type { GridColDef } from "@mui/x-data-grid";

const columns: GridColDef[] = [
  { field: "name", headerName: "Name", flex: 1 },
  { field: "slug", headerName: "Slug", width: 150 },
  { field: "status", headerName: "Status", width: 100 },
  { field: "created_at", headerName: "Created", width: 180 },
];

export default function AdminTenantsPage() {
  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>Tenants</Typography>
      <DataTable columns={columns} rows={[]} emptyMessage="No tenants found" />
    </Box>
  );
}
