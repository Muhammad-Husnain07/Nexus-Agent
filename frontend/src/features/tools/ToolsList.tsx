import { useState, useMemo } from "react"
import Box from "@mui/material/Box"
import TextField from "@mui/material/TextField"
import Button from "@mui/material/Button"
import Table from "@mui/material/Table"
import TableHead from "@mui/material/TableHead"
import TableBody from "@mui/material/TableBody"
import TableRow from "@mui/material/TableRow"
import TableCell from "@mui/material/TableCell"
import TableContainer from "@mui/material/TableContainer"
import Paper from "@mui/material/Paper"
import IconButton from "@mui/material/IconButton"
import Tooltip from "@mui/material/Tooltip"
import Chip from "@mui/material/Chip"
import CircularProgress from "@mui/material/CircularProgress"
import Alert from "@mui/material/Alert"
import Dialog from "@mui/material/Dialog"
import DialogTitle from "@mui/material/DialogTitle"
import DialogContent from "@mui/material/DialogContent"
import DialogActions from "@mui/material/DialogActions"
import Typography from "@mui/material/Typography"
import { Plus, Search, Edit, Trash2, Beaker } from "lucide-react"
import { toast } from "sonner"
import TableSkeleton from "@/components/skeletons/TableSkeleton"
import { useGetTools, useCreateTool, useUpdateTool, useDeleteTool } from "@/lib/api/tools"
import type { ToolRead, ToolCreate } from "@/lib/types"
import ToolFormDialog, { type ToolFormValues } from "./ToolFormDialog"
import ToolTestDialog from "./ToolTestDialog"

const methodColors: Record<string, "success" | "info" | "warning" | "error" | "default"> = {
  GET: "success", POST: "info", PUT: "warning", DELETE: "error", PATCH: "default",
}

const riskColors: Record<string, "success" | "warning" | "error"> = {
  low: "success", medium: "warning", high: "error",
}

export default function ToolsList() {
  const { data, isLoading, isError, error } = useGetTools()
  const createMutation = useCreateTool()
  const updateMutation = useUpdateTool()
  const deleteMutation = useDeleteTool()

  const [search, setSearch] = useState("")
  const [formOpen, setFormOpen] = useState(false)
  const [editingTool, setEditingTool] = useState<ToolRead | null>(null)
  const [testingTool, setTestingTool] = useState<ToolRead | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<ToolRead | null>(null)

  const filtered = useMemo(() => {
    if (!data?.items) return []
    const q = search.toLowerCase()
    return data.items.filter((t) =>
      t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q) || t.endpoint_url.toLowerCase().includes(q),
    )
  }, [data, search])

  const handleCreate = () => { setEditingTool(null); setFormOpen(true) }
  const handleEdit = (tool: ToolRead) => { setEditingTool(tool); setFormOpen(true) }

  const handleFormSubmit = async (formData: ToolFormValues) => {
    const payload: ToolCreate = {
      name: formData.name, description: formData.description, purpose: formData.purpose,
      endpoint_url: formData.endpoint_url, http_method: formData.http_method,
      auth_type: formData.auth_type, risk_level: formData.risk_level,
      requires_approval: formData.requires_approval,
      input_schema: JSON.parse(formData.input_schema), output_schema: JSON.parse(formData.output_schema),
    }
    try {
      if (editingTool) {
        await updateMutation.mutateAsync({ id: editingTool.id, data: payload })
        toast.success("Tool updated")
      } else {
        await createMutation.mutateAsync(payload)
        toast.success("Tool registered")
      }
      setFormOpen(false); setEditingTool(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Operation failed")
    }
  }

  const handleDeleteConfirm = async () => {
    if (!deleteConfirm) return
    try {
      await deleteMutation.mutateAsync(deleteConfirm.id)
      toast.success("Tool deleted")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed")
    }
    setDeleteConfirm(null)
  }

  if (isLoading) return <TableSkeleton rows={5} columns={6} />
  if (isError) return <Alert severity="error">{(error as Error)?.message || "Failed to load tools"}</Alert>

  return (
    <div>
      <Box sx={{ display: "flex", alignItems: "center", gap: 2, mb: 2 }}>
        <TextField
          placeholder="Search tools..."
          size="small"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          slotProps={{ input: { startAdornment: <Search size={18} style={{ marginRight: 8, opacity: 0.5 }} /> } }}
          sx={{ minWidth: 300 }}
        />
        <Box sx={{ flex: 1 }} />
        <Button variant="contained" startIcon={<Plus size={18} />} onClick={handleCreate}>
          Register Tool
        </Button>
      </Box>

      {filtered.length === 0 ? (
        <Box sx={{ textAlign: "center", py: 10, color: "text.secondary" }}>
          <Typography variant="body2">
            {search ? "No tools match your search." : "No tools registered yet. Click 'Register Tool' to add one."}
          </Typography>
        </Box>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table>
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 600 }}>Name</TableCell>
                <TableCell sx={{ fontWeight: 600 }}>Method</TableCell>
                <TableCell sx={{ fontWeight: 600 }}>Endpoint</TableCell>
                <TableCell sx={{ fontWeight: 600 }}>Risk Level</TableCell>
                <TableCell sx={{ fontWeight: 600 }}>Status</TableCell>
                <TableCell sx={{ fontWeight: 600 }} align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {filtered.map((tool) => (
                <TableRow key={tool.id} hover>
                  <TableCell sx={{ fontWeight: 500 }}>{tool.name}</TableCell>
                  <TableCell>
                    <Chip label={tool.http_method} size="small" color={methodColors[tool.http_method] ?? "default"} variant="outlined" />
                  </TableCell>
                  <TableCell sx={{ maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {tool.endpoint_url || "\u2014"}
                  </TableCell>
                  <TableCell>
                    <Chip label={tool.risk_level} size="small" color={riskColors[tool.risk_level] ?? "default"} />
                  </TableCell>
                  <TableCell>
                    <Chip label={tool.enabled ? "Enabled" : "Disabled"} size="small" color={tool.enabled ? "success" : "default"} variant="outlined" />
                  </TableCell>
                  <TableCell align="right">
                    <Tooltip title="Edit"><IconButton size="small" onClick={() => handleEdit(tool)}><Edit size={16} /></IconButton></Tooltip>
                    <Tooltip title="Test"><IconButton size="small" onClick={() => setTestingTool(tool)}><Beaker size={16} /></IconButton></Tooltip>
                    <Tooltip title="Delete"><IconButton size="small" color="error" onClick={() => setDeleteConfirm(tool)}><Trash2 size={16} /></IconButton></Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <ToolFormDialog open={formOpen} onClose={() => { setFormOpen(false); setEditingTool(null) }}
        onSubmit={handleFormSubmit} tool={editingTool} isSubmitting={createMutation.isPending || updateMutation.isPending} />
      {testingTool && <ToolTestDialog open={!!testingTool} onClose={() => setTestingTool(null)} tool={testingTool} />}

      <Dialog open={!!deleteConfirm} onClose={() => setDeleteConfirm(null)}>
        <DialogTitle>Delete Tool</DialogTitle>
        <DialogContent>Are you sure you want to delete <strong>{deleteConfirm?.name}</strong>? This action cannot be undone.</DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteConfirm(null)}>Cancel</Button>
          <Button variant="contained" color="error" onClick={handleDeleteConfirm} disabled={deleteMutation.isPending}>
            {deleteMutation.isPending ? <CircularProgress size={20} /> : "Delete"}
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  )
}
