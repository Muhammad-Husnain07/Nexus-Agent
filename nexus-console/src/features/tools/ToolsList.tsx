import { useState, useCallback } from "react"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import IconButton from "@mui/material/IconButton"
import Skeleton from "@mui/material/Skeleton"
import Dialog from "@mui/material/Dialog"
import DialogTitle from "@mui/material/DialogTitle"
import DialogContent from "@mui/material/DialogContent"
import DialogActions from "@mui/material/DialogActions"
import Typography from "@mui/material/Typography"
import { DataGrid, GridToolbar, type GridColDef, type GridRenderCellParams } from "@mui/x-data-grid"
import CheckIcon from "@mui/icons-material/Check"
import CloseIcon from "@mui/icons-material/Close"
import EditIcon from "@mui/icons-material/Edit"
import DeleteIcon from "@mui/icons-material/Delete"
import ScienceIcon from "@mui/icons-material/Science"
import MoreVertIcon from "@mui/icons-material/MoreVert"
import Menu from "@mui/material/Menu"
import MenuItem from "@mui/material/MenuItem"
import CircularProgress from "@mui/material/CircularProgress"
import { useSnackbar } from "notistack"
import { useGetTools, useCreateTool, useUpdateTool, useDeleteTool } from "@/lib/api/tools"
import type { ToolRead, ToolCreate } from "@/lib/types"
import ToolFormDialog, { type ToolFormValues } from "./ToolFormDialog"
import ToolTestDialog from "./ToolTestDialog"

const methodColors: Record<string, "success" | "info" | "warning" | "error" | "default"> = {
  GET: "success", POST: "info", PUT: "warning", DELETE: "error", PATCH: "default",
}

export default function ToolsList() {
  const { data, isLoading, isError, error } = useGetTools()
  const createMutation = useCreateTool()
  const updateMutation = useUpdateTool()
  const deleteMutation = useDeleteTool()
  const { enqueueSnackbar } = useSnackbar()

  const [formOpen, setFormOpen] = useState(false)
  const [editingTool, setEditingTool] = useState<ToolRead | null>(null)
  const [testingTool, setTestingTool] = useState<ToolRead | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<ToolRead | null>(null)
  const [menuAnchor, setMenuAnchor] = useState<{ el: HTMLElement; tool: ToolRead } | null>(null)
  const setSelectedIds = useState<(string | number)[]>([])[1]

  const columns: GridColDef[] = [
    { field: "name", headerName: "Name", flex: 1 },
    {
      field: "http_method", headerName: "Method", width: 100,
      renderCell: (params: GridRenderCellParams) => (
        <Chip label={params.value} size="small" color={methodColors[params.value as string] ?? "default"} variant="outlined" />
      ),
    },
    { field: "endpoint_url", headerName: "Endpoint", flex: 1.5,
      renderCell: (params: GridRenderCellParams) => (
        <Typography variant="body2" noWrap sx={{ maxWidth: "100%" }}>{params.value || "\u2014"}</Typography>
      ),
    },
    {
      field: "risk_level", headerName: "Risk", width: 100,
      renderCell: (params: GridRenderCellParams) => (
        <Chip label={params.value} size="small" color={params.value === "high" ? "error" : params.value === "medium" ? "warning" : "success"} />
      ),
    },
    {
      field: "requires_approval", headerName: "Approval", width: 90,
      renderCell: (params: GridRenderCellParams) => params.value ? <CheckIcon color="success" fontSize="small" /> : <CloseIcon color="disabled" fontSize="small" />,
    },
    {
      field: "enabled", headerName: "Enabled", width: 90, type: "boolean", editable: true,
    },
    {
      field: "actions", headerName: "", width: 60, sortable: false, filterable: false,
      renderCell: (params: GridRenderCellParams) => (
        <IconButton size="small" onClick={(e) => { e.stopPropagation(); setMenuAnchor({ el: e.currentTarget, tool: params.row }) }} aria-label="tool actions">
          <MoreVertIcon fontSize="small" />
        </IconButton>
      ),
    },
  ]

  // useCallback removed - unused
  const handleRowSelection = useCallback((ids: any) => setSelectedIds(ids), [])
  const handleEdit = useCallback((tool: ToolRead) => { setEditingTool(tool); setFormOpen(true); setMenuAnchor(null) }, [])

  const handleFormSubmit = useCallback(async (formData: ToolFormValues) => {
    const payload: ToolCreate = {
      name: formData.name, description: formData.description, purpose: formData.purpose,
      endpoint_url: formData.endpoint_url, http_method: formData.http_method,
      auth_type: formData.auth_type, risk_level: formData.risk_level,
      requires_approval: formData.requires_approval,
      input_schema: JSON.parse(formData.input_schema), output_schema: JSON.parse(formData.output_schema),
    }
    try {
      if (editingTool) { await updateMutation.mutateAsync({ id: editingTool.id, data: payload }); enqueueSnackbar("Tool updated", { variant: "success" }) }
      else { await createMutation.mutateAsync(payload); enqueueSnackbar("Tool registered", { variant: "success" }) }
      setFormOpen(false); setEditingTool(null)
    } catch (err) { enqueueSnackbar(err instanceof Error ? err.message : "Operation failed", { variant: "error" }) }
  }, [editingTool, createMutation, updateMutation, enqueueSnackbar])

  const handleDelete = useCallback(async () => {
    if (!deleteConfirm) return
    try { await deleteMutation.mutateAsync(deleteConfirm.id); enqueueSnackbar("Tool deleted", { variant: "success" }) }
    catch (err) { enqueueSnackbar(err instanceof Error ? err.message : "Delete failed", { variant: "error" }) }
    setDeleteConfirm(null)
  }, [deleteConfirm, deleteMutation, enqueueSnackbar])

  if (isLoading) return <Skeleton variant="rectangular" height={400} />
  if (isError) return <Typography color="error">{(error as Error)?.message || "Failed to load tools"}</Typography>

  return (
    <Box>
      <DataGrid
        rows={data?.items || []}
        columns={columns}
        pageSizeOptions={[10, 25, 50]}
        initialState={{ pagination: { paginationModel: { pageSize: 10 } } }}
        checkboxSelection
        disableRowSelectionOnClick
        onRowSelectionModelChange={handleRowSelection}
        slots={{ toolbar: GridToolbar }}
        slotProps={{ toolbar: { showQuickFilter: true } }}
        onRowClick={(params) => handleEdit(params.row as ToolRead)}
        getRowId={(row) => row.id}
        autoHeight
        sx={{ "& .MuiDataGrid-cell:focus": { outline: "none" } }}
      />

      <Menu anchorEl={menuAnchor?.el} open={!!menuAnchor} onClose={() => setMenuAnchor(null)}>
        <MenuItem onClick={() => handleEdit(menuAnchor!.tool)}><EditIcon fontSize="small" sx={{ mr: 1 }} /> Edit</MenuItem>
        <MenuItem onClick={() => { setTestingTool(menuAnchor!.tool); setMenuAnchor(null) }}><ScienceIcon fontSize="small" sx={{ mr: 1 }} /> Test</MenuItem>
        <MenuItem onClick={() => { setDeleteConfirm(menuAnchor!.tool); setMenuAnchor(null) }}><DeleteIcon fontSize="small" sx={{ mr: 1 }} /> Delete</MenuItem>
      </Menu>

      <ToolFormDialog open={formOpen} onClose={() => { setFormOpen(false); setEditingTool(null) }}
        onSubmit={handleFormSubmit} tool={editingTool} isSubmitting={createMutation.isPending || updateMutation.isPending} />
      {testingTool && <ToolTestDialog open={!!testingTool} onClose={() => setTestingTool(null)} tool={testingTool} />}

      <Dialog open={!!deleteConfirm} onClose={() => setDeleteConfirm(null)}>
        <DialogTitle>Delete Tool</DialogTitle>
        <DialogContent>Are you sure you want to delete <strong>{deleteConfirm?.name}</strong>? This action cannot be undone.</DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteConfirm(null)}>Cancel</Button>
          <Button variant="contained" color="error" onClick={handleDelete} disabled={deleteMutation.isPending}>
            {deleteMutation.isPending ? <CircularProgress size={20} /> : "Delete"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
