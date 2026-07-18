import { useState } from "react"
import { useNavigate } from "react-router-dom"
import Box from "@mui/material/Box"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import IconButton from "@mui/material/IconButton"
import Skeleton from "@mui/material/Skeleton"
import Dialog from "@mui/material/Dialog"
import DialogTitle from "@mui/material/DialogTitle"
import DialogContent from "@mui/material/DialogContent"
import DialogActions from "@mui/material/DialogActions"
import TextField from "@mui/material/TextField"
import Typography from "@mui/material/Typography"
import { DataGrid, GridToolbar, type GridColDef, type GridRenderCellParams } from "@mui/x-data-grid"
import MoreVertIcon from "@mui/icons-material/MoreVert"
import Menu from "@mui/material/Menu"
import MenuItem from "@mui/material/MenuItem"
import CircularProgress from "@mui/material/CircularProgress"
import { useSnackbar } from "notistack"
import { useGetSessions, useUpdateSession, useArchiveSession, useForkSession, useGetMessages } from "@/lib/api/sessions"
import type { SessionRead } from "@/lib/types"

function formatDistance(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

export default function SessionsList() {
  const navigate = useNavigate()
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(20)
  const { data, isLoading, isError, error } = useGetSessions({ page: page + 1, page_size: pageSize })
  const updateMutation = useUpdateSession()
  const archiveMutation = useArchiveSession()
  const forkMutation = useForkSession()
  const { enqueueSnackbar } = useSnackbar()

  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState("")
  const [archiveConfirm, setArchiveConfirm] = useState<SessionRead | null>(null)
  const [forkDialog, setForkDialog] = useState<SessionRead | null>(null)
  const [forkTitle, setForkTitle] = useState("")
  const [menuAnchor, setMenuAnchor] = useState<{ el: HTMLElement; session: SessionRead } | null>(null)
  const { data: forkMessages } = useGetMessages(forkDialog?.id ?? null, { page: 1 })

  const columns: GridColDef[] = [
    { field: "title", headerName: "Title", flex: 1,
      renderCell: (params: GridRenderCellParams) => {
        const sid = (params.row as SessionRead).id
        return (
          <span onClick={() => navigate(`/chat/${sid}`)} style={{ cursor: "pointer", color: "inherit", textDecoration: "none" }}>
            {params.value}
          </span>
        )
      },
    },
    { field: "status", headerName: "Status", width: 100,
      renderCell: (params: GridRenderCellParams) => (
        <Chip label={params.value} size="small" color={params.value === "active" ? "success" : "default"} variant="outlined" />
      ),
    },
    { field: "message_count", headerName: "Messages", width: 90, type: "number" },
    { field: "created_at", headerName: "Created", width: 130,
      renderCell: (params: GridRenderCellParams) => <span>{formatDistance(params.value as string)}</span>,
    },
    { field: "updated_at", headerName: "Updated", width: 130,
      renderCell: (params: GridRenderCellParams) => <span>{formatDistance(params.value as string)}</span>,
    },
    {
      field: "actions", headerName: "", width: 60, sortable: false, filterable: false,
      renderCell: (params: GridRenderCellParams) => (
        <IconButton size="small" onClick={(e) => { e.stopPropagation(); setMenuAnchor({ el: e.currentTarget, session: params.row }) }} aria-label="session actions">
          <MoreVertIcon fontSize="small" />
        </IconButton>
      ),
    },
  ]

  const handleRename = async () => {
    if (!menuAnchor || !editValue.trim()) return
    try { await updateMutation.mutateAsync({ id: menuAnchor.session.id, data: { title: editValue.trim() } }); enqueueSnackbar("Renamed", { variant: "success" }) }
    catch (err) { enqueueSnackbar(err instanceof Error ? err.message : "Rename failed", { variant: "error" }) }
    setEditingId(null); setMenuAnchor(null)
  }

  const handleArchive = async () => {
    if (!archiveConfirm) return
    try { await archiveMutation.mutateAsync(archiveConfirm.id); enqueueSnackbar("Archived", { variant: "success" }) }
    catch (err) { enqueueSnackbar(err instanceof Error ? err.message : "Archive failed", { variant: "error" }) }
    setArchiveConfirm(null)
  }

  const handleFork = async () => {
    if (!forkDialog) return
    const lastMsg = forkMessages?.items?.[forkMessages.items.length - 1]
    if (!lastMsg) { enqueueSnackbar("No messages to fork", { variant: "error" }); return }
    try {
      const ns = await forkMutation.mutateAsync({ id: forkDialog.id, data: { message_id: lastMsg.id, new_title: forkTitle || undefined } })
      enqueueSnackbar("Forked", { variant: "success" }); setForkDialog(null); navigate(`/chat/${ns.id}`)
    } catch (err) { enqueueSnackbar(err instanceof Error ? err.message : "Fork failed", { variant: "error" }) }
  }

  if (isLoading) return <Skeleton variant="rectangular" height={400} />
  if (isError) return <Typography color="error">{(error as Error)?.message || "Failed to load sessions"}</Typography>

  return (
    <Box>
      <DataGrid
        rows={data?.items || []}
        columns={columns}
        rowCount={data?.total || 0}
        paginationMode="server"
        pageSizeOptions={[10, 20, 50]}
        paginationModel={{ page, pageSize }}
        onPaginationModelChange={(m) => { setPage(m.page); setPageSize(m.pageSize) }}
        slots={{ toolbar: GridToolbar }}
        slotProps={{ toolbar: { showQuickFilter: true } }}
        getRowId={(row) => row.id}
        autoHeight
        sx={{ "& .MuiDataGrid-cell:focus": { outline: "none" } }}
      />

      <Menu anchorEl={menuAnchor?.el} open={!!menuAnchor} onClose={() => setMenuAnchor(null)}>
        <MenuItem onClick={() => { navigate(`/chat/${menuAnchor!.session.id}`); setMenuAnchor(null) }}>Open</MenuItem>
        <MenuItem onClick={() => { setEditingId(menuAnchor!.session.id); setEditValue(menuAnchor!.session.title); setMenuAnchor(null) }}>Rename</MenuItem>
        <MenuItem onClick={() => { setForkDialog(menuAnchor!.session); setForkTitle(`Copy of ${menuAnchor!.session.title}`); setMenuAnchor(null) }}>Fork</MenuItem>
        <MenuItem onClick={() => { setArchiveConfirm(menuAnchor!.session); setMenuAnchor(null) }}>Archive</MenuItem>
      </Menu>

      <Dialog open={!!editingId} onClose={() => setEditingId(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Rename Session</DialogTitle>
        <DialogContent sx={{ pt: "8px !important" }}>
          <TextField size="small" value={editValue} onChange={(e) => setEditValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleRename() }} fullWidth autoFocus />
        </DialogContent>
        <DialogActions><Button onClick={() => setEditingId(null)}>Cancel</Button>
          <Button variant="contained" onClick={handleRename}>Save</Button></DialogActions>
      </Dialog>

      <Dialog open={!!archiveConfirm} onClose={() => setArchiveConfirm(null)}>
        <DialogTitle>Archive Session</DialogTitle>
        <DialogContent>Are you sure you want to archive <strong>{archiveConfirm?.title}</strong>?</DialogContent>
        <DialogActions><Button onClick={() => setArchiveConfirm(null)}>Cancel</Button>
          <Button variant="contained" color="error" onClick={handleArchive} disabled={archiveMutation.isPending}>
            {archiveMutation.isPending ? <CircularProgress size={20} /> : "Archive"}
          </Button></DialogActions>
      </Dialog>

      <Dialog open={!!forkDialog} onClose={() => setForkDialog(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Fork Session</DialogTitle>
        <DialogContent sx={{ pt: "8px !important" }}>
          <TextField label="New title" size="small" value={forkTitle} onChange={(e) => setForkTitle(e.target.value)} fullWidth autoFocus />
        </DialogContent>
        <DialogActions><Button onClick={() => setForkDialog(null)}>Cancel</Button>
          <Button variant="contained" onClick={handleFork} disabled={forkMutation.isPending}>
            {forkMutation.isPending ? <CircularProgress size={20} /> : "Fork"}
          </Button></DialogActions>
      </Dialog>
    </Box>
  )
}
