import { useState } from "react"
import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import Card from "@mui/material/Card"
import CardActions from "@mui/material/CardActions"
import CardContent from "@mui/material/CardContent"
import CircularProgress from "@mui/material/CircularProgress"
import Dialog from "@mui/material/Dialog"
import DialogTitle from "@mui/material/DialogTitle"
import DialogContent from "@mui/material/DialogContent"
import DialogActions from "@mui/material/DialogActions"
import TextField from "@mui/material/TextField"
import SecurityIcon from "@mui/icons-material/Security"
import CheckIcon from "@mui/icons-material/Check"
import CloseIcon from "@mui/icons-material/Close"
import EditIcon from "@mui/icons-material/Edit"
import Editor from "@monaco-editor/react"
import { useSnackbar } from "notistack"
import { useDecideApproval } from "@/lib/api/approvals"
import { useThemeStore } from "@/theme/themeStore"
import type { ApprovalData } from "./chatStore"

interface ApprovalCardProps {
  data: ApprovalData
  onDone: () => void
}

type Decision = "pending" | "approved" | "rejected" | "edited"

export default function ApprovalCard({ data, onDone }: ApprovalCardProps) {
  const [decision, setDecision] = useState<Decision>("pending")
  const [rejectOpen, setRejectOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [rejectComment, setRejectComment] = useState("")
  const [editedInputs, setEditedInputs] = useState(JSON.stringify(data.inputs, null, 2))
  const decideMutation = useDecideApproval()
  const { enqueueSnackbar } = useSnackbar()
  const mode = useThemeStore((s) => s.mode)

  const handleApprove = async () => {
    try {
      await decideMutation.mutateAsync({ approvalId: data.approval_id, data: { action: "approve" } })
      setDecision("approved"); enqueueSnackbar("Approved", { variant: "success" }); onDone()
    } catch (err) { enqueueSnackbar(err instanceof Error ? err.message : "Failed", { variant: "error" }) }
  }

  const handleReject = async () => {
    try {
      await decideMutation.mutateAsync({ approvalId: data.approval_id, data: { action: "reject", comment: rejectComment || undefined } })
      setDecision("rejected"); setRejectOpen(false); enqueueSnackbar("Rejected", { variant: "info" }); onDone()
    } catch (err) { enqueueSnackbar(err instanceof Error ? err.message : "Failed", { variant: "error" }) }
  }

  const handleEdit = async () => {
    try {
      const parsed = JSON.parse(editedInputs)
      await decideMutation.mutateAsync({ approvalId: data.approval_id, data: { action: "edit", edited_inputs: parsed } })
      setDecision("edited"); setEditOpen(false); enqueueSnackbar("Edited and approved", { variant: "success" }); onDone()
    } catch { enqueueSnackbar("Invalid JSON", { variant: "error" }) }
  }

  if (decision !== "pending") {
    return (
      <Box sx={{ display: "flex", justifyContent: "flex-start" }}>
        <Card variant="outlined" sx={{
          borderLeft: 4, borderColor: decision === "rejected" ? "error.main" : "success.main",
          bgcolor: decision === "rejected" ? "error.light" : "success.light", opacity: 0.8, maxWidth: "80%",
        }}>
          <CardContent>
            <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
              {decision === "approved" && "✅ Approved"}
              {decision === "edited" && "✅ Approved (edited)"}
              {decision === "rejected" && "❌ Rejected"}
            </Typography>
            <Typography variant="caption">Tool: {data.tool_name}</Typography>
          </CardContent>
        </Card>
      </Box>
    )
  }

  return (
    <Box sx={{ display: "flex", justifyContent: "flex-start" }}>
      <Card variant="outlined" sx={{ borderLeft: 4, borderColor: "warning.main", maxWidth: "80%", width: "100%" }}>
        <CardContent>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1 }}>
            <SecurityIcon color="warning" />
            <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>Approval Required</Typography>
            <Chip label={data.risk_level} size="small" color={data.risk_level === "high" ? "error" : data.risk_level === "medium" ? "warning" : "success"} />
          </Box>
          <Typography variant="body2" sx={{ fontWeight: 500 }}>Tool: {data.tool_name}</Typography>
          {data.description && <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>{data.description}</Typography>}
          <Box sx={{ mt: 1 }}>
            <Typography variant="caption" color="text.secondary">Inputs:</Typography>
            <Box component="pre" sx={{ bgcolor: "grey.100", p: 1, borderRadius: 1, overflowX: "auto", typography: "caption" }}>
              {JSON.stringify(data.inputs, null, 2)}
            </Box>
          </Box>
        </CardContent>
        <CardActions>
          <Button variant="contained" color="success" size="small" startIcon={<CheckIcon />} onClick={handleApprove} disabled={decideMutation.isPending}>
            {decideMutation.isPending ? <CircularProgress size={16} /> : "Approve"}
          </Button>
          <Button variant="outlined" color="error" size="small" startIcon={<CloseIcon />} onClick={() => setRejectOpen(true)} disabled={decideMutation.isPending}>
            Reject
          </Button>
          <Button variant="text" size="small" startIcon={<EditIcon />} onClick={() => setEditOpen(true)} disabled={decideMutation.isPending}>
            Edit Inputs
          </Button>
        </CardActions>
      </Card>

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
            onChange={(v) => setEditedInputs(v ?? "{}")}
            theme={mode === "dark" ? "vs-dark" : "light"}
            options={{ minimap: { enabled: false }, fontSize: 13 }} />
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
