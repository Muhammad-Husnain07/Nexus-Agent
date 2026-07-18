import { useState } from "react"
import { useNavigate } from "react-router-dom"
import Box from "@mui/material/Box"
import Table from "@mui/material/Table"
import TableHead from "@mui/material/TableHead"
import TableBody from "@mui/material/TableBody"
import TableRow from "@mui/material/TableRow"
import TableCell from "@mui/material/TableCell"
import TableContainer from "@mui/material/TableContainer"
import Paper from "@mui/material/Paper"
import Chip from "@mui/material/Chip"
import Button from "@mui/material/Button"
import Typography from "@mui/material/Typography"
import CircularProgress from "@mui/material/CircularProgress"
import Alert from "@mui/material/Alert"
import Dialog from "@mui/material/Dialog"
import DialogTitle from "@mui/material/DialogTitle"
import DialogContent from "@mui/material/DialogContent"
import DialogActions from "@mui/material/DialogActions"
import TextField from "@mui/material/TextField"
import { ExternalLink } from "lucide-react"
import { toast } from "sonner"
import TableSkeleton from "@/components/skeletons/TableSkeleton"
import { useGetAllPendingApprovals, useDecideApproval } from "@/lib/api/approvals"
import { useGetSessions } from "@/lib/api/sessions"
import type { ApprovalRead } from "@/lib/types"

const riskColors: Record<string, "success" | "warning" | "error"> = {
  low: "success", medium: "warning", high: "error",
}

export default function ApprovalsList() {
  const navigate = useNavigate()
  const { data: approvals, isLoading, isError, error } = useGetAllPendingApprovals()
  const { data: sessionsData } = useGetSessions({ page_size: 100, status: "active" })
  const decideMutation = useDecideApproval()

  const [rejectDialog, setRejectDialog] = useState<{ approvalId: string; comment: string } | null>(null)

  const sessionMap = new Map(sessionsData?.items.map((s) => [s.id, s.title]) ?? [])

  const handleApprove = async (approvalId: string) => {
    try {
      await decideMutation.mutateAsync({ approvalId, data: { action: "approve" } })
      toast.success("Approval approved")
    } catch (err) { toast.error(err instanceof Error ? err.message : "Failed to approve") }
  }

  const handleRejectOpen = (approvalId: string) => setRejectDialog({ approvalId, comment: "" })

  const handleRejectConfirm = async () => {
    if (!rejectDialog) return
    try {
      await decideMutation.mutateAsync({ approvalId: rejectDialog.approvalId, data: { action: "reject", comment: rejectDialog.comment || undefined } })
      toast.success("Approval rejected")
    } catch (err) { toast.error(err instanceof Error ? err.message : "Failed to reject") }
    setRejectDialog(null)
  }

  const getSessionId = (approval: ApprovalRead): string | undefined => {
    const tc = approval.tool_call || {}
    return (tc.session_id as string) || undefined
  }

  if (isLoading) return <TableSkeleton rows={5} columns={5} />
  if (isError) return <Alert severity="error">{(error as Error)?.message || "Failed to load approvals"}</Alert>
  if (!approvals || approvals.length === 0) {
    return <Box sx={{ textAlign: "center", py: 10, color: "text.secondary" }}><Typography variant="body2">No pending approvals.</Typography></Box>
  }

  return (
    <div>
      <TableContainer component={Paper} variant="outlined">
        <Table>
          <TableHead>
            <TableRow>
              <TableCell sx={{ fontWeight: 600 }}>Session</TableCell>
              <TableCell sx={{ fontWeight: 600 }}>Tool</TableCell>
              <TableCell sx={{ fontWeight: 600 }}>Risk</TableCell>
              <TableCell sx={{ fontWeight: 600 }}>Created</TableCell>
              <TableCell sx={{ fontWeight: 600 }} align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {approvals.map((approval) => {
              const tc = approval.tool_call || {}
              const sessionId = getSessionId(approval)
              const sessionTitle = sessionId ? (sessionMap.get(sessionId) || sessionId.slice(0, 8) + "...") : "Unknown"

              return (
                <TableRow key={approval.id} hover>
                  <TableCell>
                    <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
                      <Typography variant="body2">{sessionTitle}</Typography>
                      {sessionId && (
                        <Box component="button" onClick={() => navigate(`/chat/${sessionId}`)}
                          sx={{ border: "none", bgcolor: "transparent", cursor: "pointer", color: "text.secondary", "&:hover": { color: "text.primary" } }}>
                          <ExternalLink size={14} />
                        </Box>
                      )}
                    </Box>
                  </TableCell>
                  <TableCell>{(tc.tool_name as string) || "\u2014"}</TableCell>
                  <TableCell>
                    <Chip label={(tc.risk_level as string) || "unknown"} size="small" color={riskColors[(tc.risk_level as string)] ?? "default"} />
                  </TableCell>
                  <TableCell><Typography variant="body2" color="text.secondary">{new Date(approval.created_at).toLocaleString()}</Typography></TableCell>
                  <TableCell align="right">
                    <Box sx={{ display: "flex", gap: 0.5, justifyContent: "flex-end" }}>
                      <Button size="small" variant="contained" color="success" onClick={() => handleApprove(approval.id)} disabled={decideMutation.isPending}>
                        Approve
                      </Button>
                      <Button size="small" variant="outlined" color="error" onClick={() => handleRejectOpen(approval.id)} disabled={decideMutation.isPending}>
                        Reject
                      </Button>
                    </Box>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </TableContainer>

      <Dialog open={!!rejectDialog} onClose={() => setRejectDialog(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Reject Approval</DialogTitle>
        <DialogContent sx={{ pt: "8px !important" }}>
          <TextField label="Comment (optional)" size="small" multiline rows={3} value={rejectDialog?.comment ?? ""}
            onChange={(e) => setRejectDialog((prev) => prev ? { ...prev, comment: e.target.value } : null)} fullWidth autoFocus />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRejectDialog(null)}>Cancel</Button>
          <Button variant="contained" color="error" onClick={handleRejectConfirm} disabled={decideMutation.isPending}>
            {decideMutation.isPending ? <CircularProgress size={20} /> : "Reject"}
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  )
}
