import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import Chip from "@mui/material/Chip"
import Skeleton from "@mui/material/Skeleton"
import { DataGrid, type GridColDef, type GridRenderCellParams } from "@mui/x-data-grid"
import { useGetRecentRuns } from "@/lib/api/metrics"
const statusColors: Record<string, "success" | "error" | "warning" | "info" | "default"> = {
  completed: "success", failed: "error", interrupted: "warning", running: "info", cancelled: "default",
}

export default function RecentRunsTable() {
  const { data, isLoading, isError, error } = useGetRecentRuns(20)

  const columns: GridColDef[] = [
    { field: "session_id", headerName: "Session", width: 120,
      renderCell: (params: GridRenderCellParams) => <Typography variant="caption" sx={{ fontFamily: "monospace" }}>{(params.value as string || "").slice(0, 8)}...</Typography>,
    },
    { field: "status", headerName: "Status", width: 120,
      renderCell: (params: GridRenderCellParams) => <Chip label={params.value} size="small" color={statusColors[params.value as string] ?? "default"} variant="outlined" />,
    },
    { field: "total_tokens", headerName: "Tokens", width: 100, type: "number",
      renderCell: (params: GridRenderCellParams) => (params.value as number || 0).toLocaleString(),
    },
    { field: "total_cost_usd", headerName: "Cost", width: 100, type: "number",
      renderCell: (params: GridRenderCellParams) => `$${(params.value as number || 0).toFixed(2)}`,
    },
    { field: "started_at", headerName: "Started", width: 180,
      renderCell: (params: GridRenderCellParams) => new Date(params.value as string).toLocaleString(),
    },
  ]

  if (isLoading) return <Skeleton variant="rectangular" height={400} />
  if (isError) return <Typography color="error">{(error as Error)?.message || "Failed to load"}</Typography>

  return (
    <Box>
      <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1.5 }}>Recent Runs</Typography>
      <DataGrid rows={data || []} columns={columns} getRowId={(r) => r.id}
        autoHeight pageSizeOptions={[10, 25]} disableRowSelectionOnClick
        slots={{ toolbar: () => null }}
        sx={{ "& .MuiDataGrid-cell:focus": { outline: "none" } }}
        initialState={{ pagination: { paginationModel: { pageSize: 10 } } }} />
    </Box>
  )
}
