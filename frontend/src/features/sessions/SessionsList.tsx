import { useState, useMemo } from "react"
import { useNavigate } from "react-router-dom"
import Box from "@mui/material/Box"
import TextField from "@mui/material/TextField"
import Card from "@mui/material/Card"
import CardContent from "@mui/material/CardContent"
import CardActions from "@mui/material/CardActions"
import Typography from "@mui/material/Typography"
import Chip from "@mui/material/Chip"
import IconButton from "@mui/material/IconButton"
import Menu from "@mui/material/Menu"
import MenuItem from "@mui/material/MenuItem"
import Pagination from "@mui/material/Pagination"
import CircularProgress from "@mui/material/CircularProgress"
import Alert from "@mui/material/Alert"
import Dialog from "@mui/material/Dialog"
import DialogTitle from "@mui/material/DialogTitle"
import DialogContent from "@mui/material/DialogContent"
import DialogActions from "@mui/material/DialogActions"
import Button from "@mui/material/Button"
import { Search, MoreVertical, Trash2, Copy, Edit3, ExternalLink } from "lucide-react"
import { toast } from "sonner"
import CardSkeleton from "@/components/skeletons/CardSkeleton"
import { useGetSessions, useUpdateSession, useArchiveSession, useForkSession, useGetMessages } from "@/lib/api/sessions"
import type { SessionRead } from "@/lib/types"

export default function SessionsList() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState("")
  const [menuAnchor, setMenuAnchor] = useState<{ el: HTMLElement; session: SessionRead } | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState("")
  const [archiveConfirm, setArchiveConfirm] = useState<SessionRead | null>(null)
  const [forkDialog, setForkDialog] = useState<SessionRead | null>(null)
  const [forkTitle, setForkTitle] = useState("")

  const { data, isLoading, isError, error } = useGetSessions({ page, page_size: 12 })
  const updateMutation = useUpdateSession()
  const archiveMutation = useArchiveSession()
  const forkMutation = useForkSession()
  const { data: forkMessages } = useGetMessages(forkDialog?.id ?? null, { page: 1 })

  const filtered = useMemo(() => {
    if (!data?.items) return []
    const q = search.toLowerCase()
    return data.items.filter((s) => s.title.toLowerCase().includes(q))
  }, [data, search])

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 1

  const handleOpen = (session: SessionRead) => navigate(`/chat/${session.id}`)

  const handleStartRename = (session: SessionRead) => {
    setEditingId(session.id); setEditValue(session.title); setMenuAnchor(null)
  }

  const handleSaveRename = async (sessionId: string) => {
    if (!editValue.trim()) { setEditingId(null); return }
    try {
      await updateMutation.mutateAsync({ id: sessionId, data: { title: editValue.trim() } })
      toast.success("Session renamed")
    } catch (err) { toast.error(err instanceof Error ? err.message : "Rename failed") }
    setEditingId(null)
  }

  const handleArchive = async () => {
    if (!archiveConfirm) return
    try {
      await archiveMutation.mutateAsync(archiveConfirm.id)
      toast.success("Session archived")
    } catch (err) { toast.error(err instanceof Error ? err.message : "Archive failed") }
    setArchiveConfirm(null)
  }

  const handleFork = async () => {
    if (!forkDialog) return
    const lastMsg = forkMessages?.items?.[forkMessages.items.length - 1]
    if (!lastMsg) { toast.error("No messages to fork from"); return }
    try {
      const newSession = await forkMutation.mutateAsync({
        id: forkDialog.id, data: { message_id: lastMsg.id, new_title: forkTitle || undefined },
      })
      toast.success("Session forked"); setForkDialog(null); navigate(`/chat/${newSession.id}`)
    } catch (err) { toast.error(err instanceof Error ? err.message : "Fork failed") }
  }

  const relativeTime = (iso: string) => {
    const diff = Date.now() - new Date(iso).getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return "Just now"
    if (mins < 60) return `${mins}m ago`
    const hours = Math.floor(mins / 60)
    if (hours < 24) return `${hours}h ago`
    return `${Math.floor(hours / 24)}d ago`
  }

  if (isLoading) return <CardSkeleton count={6} />
  if (isError) return <Alert severity="error">{(error as Error)?.message || "Failed to load sessions"}</Alert>

  return (
    <div>
      <Box sx={{ display: "flex", alignItems: "center", gap: 2, mb: 3 }}>
        <TextField placeholder="Search sessions..." size="small" value={search} onChange={(e) => setSearch(e.target.value)}
          slotProps={{ input: { startAdornment: <Search size={18} style={{ marginRight: 8, opacity: 0.5 }} /> } }}
          sx={{ minWidth: 300 }} />
      </Box>

      {filtered.length === 0 ? (
        <Box sx={{ textAlign: "center", py: 10, color: "text.secondary" }}>
          <Typography variant="body2">
            {search ? "No sessions match your search." : "No sessions yet. Start a conversation to create one."}
          </Typography>
        </Box>
      ) : (
        <>
          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr", lg: "1fr 1fr 1fr" }, gap: 2 }}>
            {filtered.map((session) => (
              <Card key={session.id} variant="outlined" sx={{ cursor: "pointer", "&:hover": { borderColor: "primary.main" } }}
                onClick={() => handleOpen(session)}>
                <CardContent sx={{ pb: 1 }}>
                  {editingId === session.id ? (
                    <TextField size="small" value={editValue} onChange={(e) => setEditValue(e.target.value)}
                      onBlur={() => handleSaveRename(session.id)}
                      onKeyDown={(e) => { if (e.key === "Enter") handleSaveRename(session.id); if (e.key === "Escape") setEditingId(null) }}
                      autoFocus onClick={(e) => e.stopPropagation()} fullWidth />
                  ) : (
                    <Typography variant="subtitle1" sx={{ fontWeight: 600 }} noWrap>{session.title}</Typography>
                  )}
                  <Box sx={{ display: "flex", alignItems: "center", gap: 1, mt: 1 }}>
                    <Chip label={session.status} size="small" color={session.status === "active" ? "success" : "default"} variant="outlined" />
                    <Typography variant="caption" color="text.secondary">{session.message_count} messages</Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ ml: "auto" }}>{relativeTime(session.updated_at)}</Typography>
                  </Box>
                </CardContent>
                <CardActions sx={{ justifyContent: "flex-end", pt: 0 }}>
                  <IconButton size="small" onClick={(e) => { e.stopPropagation(); setMenuAnchor({ el: e.currentTarget, session }) }}>
                    <MoreVertical size={16} />
                  </IconButton>
                </CardActions>
              </Card>
            ))}
          </Box>
          {totalPages > 1 && (
            <Box sx={{ display: "flex", justifyContent: "center", mt: 3 }}>
              <Pagination count={totalPages} page={page} onChange={(_, p) => setPage(p)} color="primary" />
            </Box>
          )}
        </>
      )}

      <Menu anchorEl={menuAnchor?.el} open={!!menuAnchor} onClose={() => setMenuAnchor(null)}>
        <MenuItem onClick={() => { handleOpen(menuAnchor!.session); setMenuAnchor(null) }}>
          <ExternalLink size={16} style={{ marginRight: 8 }} /> Open
        </MenuItem>
        <MenuItem onClick={() => handleStartRename(menuAnchor!.session)}>
          <Edit3 size={16} style={{ marginRight: 8 }} /> Rename
        </MenuItem>
        <MenuItem onClick={() => { setForkDialog(menuAnchor!.session); setForkTitle(`Copy of ${menuAnchor!.session.title}`); setMenuAnchor(null) }}>
          <Copy size={16} style={{ marginRight: 8 }} /> Fork
        </MenuItem>
        <MenuItem onClick={() => { setArchiveConfirm(menuAnchor!.session); setMenuAnchor(null) }}>
          <Trash2 size={16} style={{ marginRight: 8 }} /> Archive
        </MenuItem>
      </Menu>

      <Dialog open={!!archiveConfirm} onClose={() => setArchiveConfirm(null)}>
        <DialogTitle>Archive Session</DialogTitle>
        <DialogContent>Are you sure you want to archive <strong>{archiveConfirm?.title}</strong>?</DialogContent>
        <DialogActions>
          <Button onClick={() => setArchiveConfirm(null)}>Cancel</Button>
          <Button variant="contained" color="error" onClick={handleArchive} disabled={archiveMutation.isPending}>
            {archiveMutation.isPending ? <CircularProgress size={20} /> : "Archive"}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!forkDialog} onClose={() => setForkDialog(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Fork Session</DialogTitle>
        <DialogContent sx={{ pt: "8px !important" }}>
          <TextField label="New title" size="small" value={forkTitle} onChange={(e) => setForkTitle(e.target.value)} fullWidth autoFocus />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setForkDialog(null)}>Cancel</Button>
          <Button variant="contained" onClick={handleFork} disabled={forkMutation.isPending}>
            {forkMutation.isPending ? <CircularProgress size={20} /> : "Fork"}
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  )
}
