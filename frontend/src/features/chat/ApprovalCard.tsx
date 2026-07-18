import { useState } from "react"
import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import CircularProgress from "@mui/material/CircularProgress"
import Dialog from "@mui/material/Dialog"
import DialogTitle from "@mui/material/DialogTitle"
import DialogContent from "@mui/material/DialogContent"
import DialogActions from "@mui/material/DialogActions"
import TextField from "@mui/material/TextField"
import Editor from "@monaco-editor/react"
import { useDecideApproval } from "@/lib/api/approvals"
import type { ApprovalData } from "./chatStore"

interface ApprovalCardProps {
  data: ApprovalData
  onDone: () => void
}

type Decision = "pending" | "approved" | "rejected" | "edited"

const riskColors: Record<string, "success" | "warning" | "error"> = {
  low: "success", medium: "warning", high: "error",
}

export default function ApprovalCard({ data, onDone }: ApprovalCardProps) {
  const [decision, setDecision] = useState<Decision>("pending")
  const [rejectOpen, setRejectOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [rejectComment, setRejectComment] = useState("")
  const [editedInputs, setEditedInputs] = useState(JSON.stringify(data.inputs, null, 2))
  const decideMutation = useDecideApproval()

  const handleApprove = async () => {
    try {
      await decideMutation.mutateAsync({ approvalId: data.approval_id, data: { action: "approve" } })
      setDecision("approved")
      onDone()
    } catch { /* handled by interceptor */ }
  }

  const handleReject = async () => {
    try {
      await decideMutation.mutateAsync({ approvalId: data.approval_id, data: { action: "reject", comment: rejectComment || undefined } })
      setDecision("rejected")
      setRejectOpen(false)
      onDone()
    } catch { /* handled */ }
  }

  const handleEdit = async () => {
    let parsed: Record<string, unknown>
    try { parsed = JSON.parse(editedInputs) } catch { return }
    try {
      await decideMutation.mutateAsync({ approvalId: data.approval_id, data: { action: "edit", edited_inputs: parsed } })
      setDecision("edited")
      setEditOpen(false)
      onDone()
    } catch { /* handled */ }
  }

  if (decision !== "pending") {
    return (
      <Box sx={{ display: "flex", justifyContent: "flex-start" }}>
        <Box sx={{
          borderRadius: 2, border: 1, px: 2, py: 1.5, maxWidth: "80%",
          ...(decision === "approved" || decision === "edited"
            ? { borderColor: "success.light", bgcolor: "success.light", color: "success.dark" }
            : { borderColor: "error.light", bgcolor: "error.light", color: "error.dark" }),
        }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
            {decision === "approved" && "✅ Approved"}
            {decision === "edited" && "✅ Approved (edited)"}
            {decision === "rejected" && "❌ Rejected"}
          </Typography>
          <Typography variant="caption" sx={{ opacity: 0.8 }}>Tool: {data.tool_name}</Typography>
          {rejectComment && decision === "rejected" && (
            <Typography variant="caption" sx={{ opacity: 0.8, display: "block", mt: 0.5 }}>
              Comment: {rejectComment}
            </Typography>
          )}
        </Box>
      </Box>
    )
  }

  return (
    <Box sx={{ display: "flex", justifyContent: "flex-start" }}>
      <Box sx={{ borderRadius: 2, border: 1, borderColor: "warning.main", bgcolor: "warning.light", px: 2, py: 1.5, maxWidth: "80%" }}>
        <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>⚠️ Approval Required</Typography>
          <Chip label={data.risk_level} size="small" color={riskColors[data.risk_level] ?? "default"} />
        </Box>
        <Typography variant="body2" sx={{ mb: 0.5 }}><strong>Tool:</strong> {data.tool_name}</Typography>
        {data.description && <Typography variant="body2" sx={{ mb: 0.5, opacity: 0.8 }}>{data.description}</Typography>}
        <Typography variant="body2" sx={{ mb: 1 }}><strong>Inputs:</strong></Typography>
        <Box component="pre" sx={{ bgcolor: "background.default", p: 1, borderRadius: 1, overflowX: "auto", typography: "caption", mb: 1.5 }}>
          {JSON.stringify(data.inputs, null, 2)}
        </Box>
        <Box sx={{ display: "flex", gap: 1 }}>
          <Button variant="contained" color="success" size="small" onClick={handleApprove} disabled={decideMutation.isPending}>
            {decideMutation.isPending ? <CircularProgress size={16} /> : "Approve"}
          </Button>
          <Button variant="outlined" color="error" size="small" onClick={() => setRejectOpen(true)} disabled={decideMutation.isPending}>
            Reject
          </Button>
          <Button variant="outlined" size="small" onClick={() => setEditOpen(true)} disabled={decideMutation.isPending}>
            Edit Inputs
          </Button>
        </Box>
      </Box>

      <Dialog open={rejectOpen} onClose={() => setRejectOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Reject Approval</DialogTitle>
        <DialogContent sx={{ pt: "8px !important" }}>
          <TextField label="Comment (optional)" size="small" multiline rows={3} value={rejectComment}
            onChange={(e) => setRejectComment(e.target.value)} fullWidth autoFocus />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRejectOpen(false)}>Cancel</Button>
          <Button variant="contained" color="error" onClick={handleReject} disabled={decideMutation.isPending}>
            {decideMutation.isPending ? <CircularProgress size={20} /> : "Reject"}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={editOpen} onClose={() => setEditOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>Edit Inputs</DialogTitle>
        <DialogContent sx={{ pt: "8px !important" }}>
          <Editor height={300} defaultLanguage="json" value={editedInputs}
            onChange={(v) => setEditedInputs(v ?? "{}")} options={{ minimap: { enabled: false }, fontSize: 13 }} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleEdit} disabled={decideMutation.isPending}>
            {decideMutation.isPending ? <CircularProgress size={20} /> : "Save & Approve"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
