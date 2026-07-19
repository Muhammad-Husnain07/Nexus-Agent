import { DataGrid, type GridColDef, GridRowSelectionModel } from "@mui/x-data-grid";
import { Chip, IconButton, Box } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CancelIcon from "@mui/icons-material/Cancel";

interface Approval { id: string; tool_name: string; session_id: string; risk_level: string; status: string; created_at: string; }
interface Props { rows: Approval[]; loading?: boolean; onView?: (id: string) => void; onBulkApprove?: (ids: string[]) => void; onBulkReject?: (ids: string[]) => void; }

const columns: GridColDef[] = [
  { field: "tool_name", headerName: "Tool", flex: 1 },
  { field: "session_id", headerName: "Session", width: 200 },
  { field: "risk_level", headerName: "Risk", width: 100, renderCell: (p) => <Chip label={p.value} size="small" color={p.value === "high" ? "error" : "warning"} /> },
  { field: "status", headerName: "Status", width: 120, renderCell: (p) => <Chip label={p.value} size="small" variant="outlined" /> },
  { field: "created_at", headerName: "Requested", width: 180 },
];

export default function ApprovalsTable({ rows, loading, onView, onBulkApprove, onBulkReject }: Props) {
  return (
    <Box>
      <DataGrid
        rows={rows} columns={columns} loading={loading} autoHeight disableRowSelectionOnClick
        checkboxSelection onRowSelectionModelChange={(m: GridRowSelectionModel) => {
          if (onBulkApprove || onBulkReject) {
            /* toolbar would use this */
          }
        }}
        pageSizeOptions={[20, 50, 100]}
        sx={{ "& .MuiDataGrid-cell": { py: 1 } }}
      />
    </Box>
  );
}
