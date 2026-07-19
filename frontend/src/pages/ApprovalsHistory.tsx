import { Box, Typography, Button, Grid, Card, CardContent } from "@mui/material";
import { DataTable } from "../components/UI/DataTable";
import type { GridColDef } from "@mui/x-data-grid";

const columns: GridColDef[] = [
  { field: "tool_name", headerName: "Tool", flex: 1 },
  { field: "decision", headerName: "Decision", width: 120 },
  { field: "approved_by", headerName: "Approver", width: 150 },
  { field: "created_at", headerName: "Date", width: 180 },
];

export default function ApprovalsHistoryPage() {
  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>Approvals History</Typography>
      <Grid container spacing={2} mb={3}>
        {[{ label: "Approval Rate", value: "87%" }, { label: "Avg Response", value: "2.4m" }].map((s) => (
          <Grid item xs={6} sm={3} key={s.label}><Card><CardContent sx={{ textAlign: "center" }}>
            <Typography variant="h5" fontWeight={700}>{s.value}</Typography><Typography variant="caption" color="text.secondary">{s.label}</Typography>
          </CardContent></Card></Grid>
        ))}
      </Grid>
      <DataTable columns={columns} rows={[]} emptyMessage="No approval history" />
    </Box>
  );
}
