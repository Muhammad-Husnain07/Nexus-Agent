import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import Skeleton from "@mui/material/Skeleton"
import { DataGrid, type GridColDef, type GridRenderCellParams } from "@mui/x-data-grid"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"

interface AuditEntry {
  id: string; actor_id: string; action: string; resource_type: string; resource_id: string; ip: string; created_at: string
}

export default function AuditLogPage() {
  const { data, isLoading } = useQuery<AuditEntry[]>({
    queryKey: ["admin", "audit-log"],
    queryFn: () => api.get("/admin/audit-log").then((r) => r.data),
    refetchInterval: 30_000,
  })

  const columns: GridColDef[] = [
    { field: "actor_id", headerName: "Actor", width: 100, renderCell: (p: GridRenderCellParams) => <Typography variant="caption" sx={{ fontFamily: "monospace" }}>{(p.value as string || "").slice(0, 8)}...</Typography> },
    { field: "action", headerName: "Action", width: 180 },
    { field: "resource_type", headerName: "Resource", width: 120 },
    { field: "resource_id", headerName: "Resource ID", flex: 1, renderCell: (p: GridRenderCellParams) => <Typography variant="caption" sx={{ fontFamily: "monospace" }}>{(p.value as string || "").slice(0, 12)}...</Typography> },
    { field: "ip", headerName: "IP", width: 140 },
    { field: "created_at", headerName: "Timestamp", width: 200, renderCell: (p: GridRenderCellParams) => new Date(p.value as string).toLocaleString() },
  ]

  return (
    <Box>
      <Typography variant="h5" sx={{ fontWeight: 700, mb: 2 }}>Audit Log</Typography>
      {isLoading ? <Skeleton variant="rectangular" height={400} /> : (
        <DataGrid rows={data || []} columns={columns} getRowId={(r) => r.id}
          autoHeight pageSizeOptions={[10, 25, 50]} disableRowSelectionOnClick
          sx={{ "& .MuiDataGrid-cell:focus": { outline: "none" } }}
          getDetailPanelContent={({ row }) => <Box sx={{ p: 2 }}><Typography variant="caption" component="pre">{JSON.stringify(row, null, 2)}</Typography></Box>}
        />
      )}
    </Box>
  )
}
