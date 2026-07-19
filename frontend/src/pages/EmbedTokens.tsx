import { Box, Typography } from "@mui/material";
import { DataTable } from "../components/UI/DataTable";
import type { GridColDef } from "@mui/x-data-grid";

const columns: GridColDef[] = [
  { field: "token", headerName: "Token", flex: 1 },
  { field: "domain", headerName: "Domain", width: 200 },
  { field: "status", headerName: "Status", width: 100 },
  { field: "created_at", headerName: "Created", width: 180 },
];

export default function EmbedTokensPage() {
  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>Embed Tokens</Typography>
      <DataTable columns={columns} rows={[]} emptyMessage="No embed tokens" />
    </Box>
  );
}
