import { useState } from "react"
import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import Dialog from "@mui/material/Dialog"
import DialogTitle from "@mui/material/DialogTitle"
import DialogContent from "@mui/material/DialogContent"
import DialogActions from "@mui/material/DialogActions"
import Button from "@mui/material/Button"
import CircularProgress from "@mui/material/CircularProgress"
import Alert from "@mui/material/Alert"
import Editor from "@monaco-editor/react"
import { toast } from "sonner"
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

  const handleExecute = async () => {
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(sampleInput)
    } catch {
      toast.error("Sample input contains invalid JSON")
      return
    }

    try {
      const res = await testMutation.mutateAsync({ id: tool.id, sampleInput: parsed })
      setResult(res)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Test failed")
    }
  }

  const handleClose = () => {
    setResult(null)
    setSampleInput("{}")
    onClose()
  }

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle>Test Tool: {tool.name}</DialogTitle>
      <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, pt: "8px !important" }}>
        <div>
          <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>Sample Input (JSON)</Typography>
          <Editor
            height={150}
            defaultLanguage="json"
            value={sampleInput}
            onChange={(v) => setSampleInput(v ?? "{}")}
            options={{ minimap: { enabled: false }, fontSize: 13 }}
          />
        </div>

        {result && (
          <Alert severity="success" sx={{ "& .MuiAlert-message": { width: "100%" } }}>
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>Response</Typography>
            <Box component="pre" sx={{ typography: "caption", bgcolor: "grey.100", p: 1, borderRadius: 1, overflow: "auto", maxHeight: 240 }}>
              {JSON.stringify(result, null, 2)}
            </Box>
          </Alert>
        )}

        {testMutation.isError && (
          <Alert severity="error">
            {testMutation.error instanceof Error ? testMutation.error.message : "Test failed"}
          </Alert>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>Close</Button>
        <Button
          variant="contained"
          onClick={handleExecute}
          disabled={testMutation.isPending}
        >
          {testMutation.isPending ? <CircularProgress size={20} /> : "Execute"}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
