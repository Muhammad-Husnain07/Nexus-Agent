import { Box, Typography } from "@mui/material";
import { DataTable } from "../components/UI/DataTable";
import type { GridColDef } from "@mui/x-data-grid";

const columns: GridColDef[] = [
  { field: "label", headerName: "Label", flex: 1 },
  { field: "role", headerName: "Role", width: 120 },
  { field: "created_at", headerName: "Created", width: 180 },
  { field: "last_used_at", headerName: "Last Used", width: 180 },
];

export default function AdminApiKeysPage() {
  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>API Keys</Typography>
      <DataTable columns={columns} rows={[]} emptyMessage="No API keys" />
    </Box>
  );
}
