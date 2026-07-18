import { useState } from "react"
import Box from "@mui/material/Box"
import Dialog from "@mui/material/Dialog"
import DialogTitle from "@mui/material/DialogTitle"
import DialogContent from "@mui/material/DialogContent"
import DialogActions from "@mui/material/DialogActions"
import Button from "@mui/material/Button"
import Typography from "@mui/material/Typography"
import Chip from "@mui/material/Chip"
import CircularProgress from "@mui/material/CircularProgress"
import Alert from "@mui/material/Alert"
import Editor from "@monaco-editor/react"
import { useSnackbar } from "notistack"
import { useThemeStore } from "@/theme/themeStore"
import { useTestTool } from "@/lib/api/tools"
import type { ToolRead, ToolTestResponse } from "@/lib/types"

interface ToolTestDialogProps {
  open: boolean
  onClose: () => void
  tool: ToolRead
}

export default function ToolTestDialog({ open, onClose, tool }: ToolTestDialogProps) {
  const [sampleInput, setSampleInput] = useState("{}")
  const [result, setResult] = useState<ToolTestResponse | null>(null)
  const testMutation = useTestTool()
  const { enqueueSnackbar } = useSnackbar()
  const mode = useThemeStore((s) => s.mode)

  const handleExecute = async () => {
    try {
      const parsed = JSON.parse(sampleInput)
      const res = await testMutation.mutateAsync({ id: tool.id, sampleInput: parsed })
      setResult(res)
    } catch (err) {
      if (err instanceof SyntaxError) enqueueSnackbar("Invalid JSON", { variant: "error" })
      else enqueueSnackbar(err instanceof Error ? err.message : "Test failed", { variant: "error" })
    }
  }

  const handleClose = () => { setResult(null); setSampleInput("{}"); onClose() }

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle>Test Tool: {tool.name}</DialogTitle>
      <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, pt: "8px !important" }}>
        <Typography variant="body2" sx={{ fontWeight: 500 }}>Sample Input (JSON)</Typography>
        <Editor height={200} defaultLanguage="json" value={sampleInput} onChange={(v) => setSampleInput(v ?? "{}")}
          theme={mode === "dark" ? "vs-dark" : "light"} options={{ minimap: { enabled: false }, fontSize: 13 }} />

        {result && (
          <Alert severity="success" sx={{ "& .MuiAlert-message": { width: "100%" } }}>
            <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1 }}>
              <Chip label={`HTTP ${tool.http_method}`} size="small" color="success" variant="outlined" />
              <Typography variant="caption">completed</Typography>
            </Box>
            <Typography variant="body2" sx={{ fontWeight: 500 }}>Response</Typography>
            <Box component="pre" sx={{ bgcolor: "grey.100", p: 1, borderRadius: 1, overflow: "auto", maxHeight: 240, typography: "caption" }}>
              {JSON.stringify(result, null, 2)}
            </Box>
          </Alert>
        )}

        {testMutation.isError && (
          <Alert severity="error">{testMutation.error instanceof Error ? testMutation.error.message : "Test failed"}</Alert>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>Close</Button>
        <Button variant="contained" onClick={handleExecute} disabled={testMutation.isPending}>
          {testMutation.isPending ? <CircularProgress size={20} /> : "Execute"}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
