import { useState } from "react"
import { useNavigate } from "react-router-dom"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import Typography from "@mui/material/Typography"
import Skeleton from "@mui/material/Skeleton"
import Dialog from "@mui/material/Dialog"
import DialogTitle from "@mui/material/DialogTitle"
import DialogContent from "@mui/material/DialogContent"
import DialogActions from "@mui/material/DialogActions"
import TextField from "@mui/material/TextField"
import CircularProgress from "@mui/material/CircularProgress"
import { DataGrid, type GridColDef, type GridRenderCellParams } from "@mui/x-data-grid"
import CheckIcon from "@mui/icons-material/Check"
import CloseIcon from "@mui/icons-material/Close"
import { useSnackbar } from "notistack"
import { useGetAllPendingApprovals, useDecideApproval } from "@/lib/api/approvals"
import { useGetSessions } from "@/lib/api/sessions"
import type { ApprovalRead } from "@/lib/types"

export default function ApprovalsList() {
  const navigate = useNavigate()
  const { data: approvals, isLoading, isError, error } = useGetAllPendingApprovals()
  const { data: sessionsData } = useGetSessions({ page_size: 100, status: "active" })
  const decideMutation = useDecideApproval()
  const { enqueueSnackbar } = useSnackbar()
  const [rejectDialog, setRejectDialog] = useState<{ approvalId: string; comment: string } | null>(null)

  const sessionMap = new Map(sessionsData?.items.map((s) => [s.id, s.title]) ?? [])

  const handleApprove = async (id: string) => {
    try { await decideMutation.mutateAsync({ approvalId: id, data: { action: "approve" } }); enqueueSnackbar("Approved", { variant: "success" }) }
    catch (err) { enqueueSnackbar(err instanceof Error ? err.message : "Failed", { variant: "error" }) }
  }

  const handleReject = async () => {
    if (!rejectDialog) return
    try { await decideMutation.mutateAsync({ approvalId: rejectDialog.approvalId, data: { action: "reject", comment: rejectDialog.comment || undefined } }); enqueueSnackbar("Rejected", { variant: "info" }); setRejectDialog(null) }
    catch (err) { enqueueSnackbar(err instanceof Error ? err.message : "Failed", { variant: "error" }) }
  }

  const getSessionId = (a: ApprovalRead) => (a.tool_call?.session_id as string) || undefined

  const columns: GridColDef[] = [
    { field: "session", headerName: "Session", flex: 1,
      renderCell: (params: GridRenderCellParams) => {
        const sid = getSessionId(params.row)
        const title = sid ? (sessionMap.get(sid) || sid.slice(0, 8) + "...") : "Unknown"
        return <span style={{ cursor: "pointer" }} onClick={() => sid && navigate(`/chat/${sid}`)}>{title}</span>
      },
    },
    { field: "tool", headerName: "Tool", flex: 1,
      renderCell: (params: GridRenderCellParams) => { const tc = params.row.tool_call || {}; return (tc.tool_name as string) || "\u2014" },
    },
    { field: "risk", headerName: "Risk", width: 100,
      renderCell: (params: GridRenderCellParams) => { const tc = params.row.tool_call || {}; const r = (tc.risk_level as string) || "low";
        return <Chip label={r} size="small" color={r === "high" ? "error" : r === "medium" ? "warning" : "success"} /> },
    },
    { field: "created_at", headerName: "Created", width: 180,
      renderCell: (params: GridRenderCellParams) => new Date(params.value as string).toLocaleString(),
    },
    {
      field: "actions", headerName: "Actions", width: 200, sortable: false, filterable: false,
      renderCell: (params: GridRenderCellParams) => (
        <Box sx={{ display: "flex", gap: 0.5 }}>
          <Button size="small" variant="contained" color="success" startIcon={<CheckIcon />}
            onClick={() => handleApprove(params.row.id)} disabled={decideMutation.isPending}>Approve</Button>
          <Button size="small" variant="outlined" color="error" startIcon={<CloseIcon />}
            onClick={() => setRejectDialog({ approvalId: params.row.id, comment: "" })} disabled={decideMutation.isPending}>Reject</Button>
        </Box>
      ),
    },
  ]

  if (isLoading) return <Skeleton variant="rectangular" height={400} />
  if (isError) return <Typography color="error">{(error as Error)?.message || "Failed to load approvals"}</Typography>

  return (
    <Box>
      <DataGrid rows={approvals || []} columns={columns} getRowId={(r) => r.id}
        autoHeight pageSizeOptions={[10, 25, 50]} disableRowSelectionOnClick
        slots={{ toolbar: () => null }} sx={{ "& .MuiDataGrid-cell:focus": { outline: "none" } }} />

      <Dialog open={!!rejectDialog} onClose={() => setRejectDialog(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Reject Approval</DialogTitle>
        <DialogContent sx={{ pt: "8px !important" }}>
          <TextField label="Comment (optional)" size="small" multiline rows={3}
            value={rejectDialog?.comment ?? ""}
            onChange={(e) => setRejectDialog((p) => p ? { ...p, comment: e.target.value } : null)} fullWidth autoFocus />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRejectDialog(null)}>Cancel</Button>
          <Button variant="contained" color="error" onClick={handleReject} disabled={decideMutation.isPending}>
            {decideMutation.isPending ? <CircularProgress size={20} /> : "Reject"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
