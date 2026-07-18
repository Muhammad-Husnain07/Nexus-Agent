import { useState } from "react"
import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import TextField from "@mui/material/TextField"
import Select from "@mui/material/Select"
import MenuItem from "@mui/material/MenuItem"
import FormControl from "@mui/material/FormControl"
import InputLabel from "@mui/material/InputLabel"
import Card from "@mui/material/Card"
import CardContent from "@mui/material/CardContent"
import Button from "@mui/material/Button"
import Chip from "@mui/material/Chip"
import IconButton from "@mui/material/IconButton"
import Skeleton from "@mui/material/Skeleton"
import Dialog from "@mui/material/Dialog"
import DialogTitle from "@mui/material/DialogTitle"
import DialogContent from "@mui/material/DialogContent"
import DialogActions from "@mui/material/DialogActions"
import DeleteIcon from "@mui/icons-material/Delete"
import SearchIcon from "@mui/icons-material/Search"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useSnackbar } from "notistack"
import { api } from "@/lib/api"

interface MemoryItem {
  id: string
  kind: string
  content: string
  metadata_: Record<string, unknown>
  importance: number
  created_at: string
  last_accessed_at: string
}

export default function MemoryPage() {
  const [search, setSearch] = useState("")
  const [kind, setKind] = useState("")
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const { enqueueSnackbar } = useSnackbar()

  const { data, isLoading } = useQuery<MemoryItem[]>({
    queryKey: ["memory", search, kind],
    queryFn: () =>
      api.get("/memory", { params: { q: search || undefined, kind: kind || undefined } }).then((r) => r.data),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/memory/${id}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["memory"] }); enqueueSnackbar("Memory deleted", { variant: "success" }) },
    onError: (err: Error) => enqueueSnackbar(err.message, { variant: "error" }),
  })

  const handleDelete = async () => {
    if (!deleteId) return
    await deleteMutation.mutateAsync(deleteId)
    setDeleteId(null)
  }

  return (
    <Box>
      <Typography variant="h5" sx={{ fontWeight: 700, mb: 2 }}>Memory Browser</Typography>
      <Box sx={{ display: "flex", gap: 2, mb: 3 }}>
        <TextField placeholder="Search memories..." size="small" value={search}
          onChange={(e) => setSearch(e.target.value)}
          slotProps={{ input: { startAdornment: <SearchIcon fontSize="small" sx={{ mr: 1, opacity: 0.5 }} /> } }}
          sx={{ minWidth: 300 }} />
        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel>Kind</InputLabel>
          <Select value={kind} label="Kind" onChange={(e) => setKind(e.target.value)}>
            <MenuItem value="">All</MenuItem>
            <MenuItem value="episodic">Episodic</MenuItem>
            <MenuItem value="semantic">Semantic</MenuItem>
            <MenuItem value="procedural">Procedural</MenuItem>
          </Select>
        </FormControl>
      </Box>

      {isLoading ? (
        <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" } }}>
          {[1, 2, 3, 4].map((i) => <Skeleton key={i} variant="rectangular" height={120} />)}
        </Box>
      ) : !data || data.length === 0 ? (
        <Box sx={{ textAlign: "center", py: 8, color: "text.secondary" }}>
          <Typography>No memories found.</Typography>
        </Box>
      ) : (
        <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" } }}>
          {data.map((mem) => (
            <Card key={mem.id} variant="outlined">
              <CardContent>
                <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", mb: 1 }}>
                  <Box sx={{ display: "flex", gap: 1 }}>
                    <Chip label={mem.kind} size="small" />
                    <Chip label={`${mem.importance.toFixed(1)}`} size="small" variant="outlined" />
                  </Box>
                  <IconButton size="small" color="error" onClick={() => setDeleteId(mem.id)} aria-label="delete memory">
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Box>
                <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                  {mem.content}
                </Typography>
                <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
                  Last accessed: {mem.last_accessed_at ? new Date(mem.last_accessed_at).toLocaleString() : "Never"}
                </Typography>
              </CardContent>
            </Card>
          ))}
        </Box>
      )}

      <Dialog open={!!deleteId} onClose={() => setDeleteId(null)}>
        <DialogTitle>Delete Memory</DialogTitle>
        <DialogContent>Are you sure? This cannot be undone.</DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteId(null)}>Cancel</Button>
          <Button variant="contained" color="error" onClick={handleDelete} disabled={deleteMutation.isPending}>
            {deleteMutation.isPending ? "Deleting..." : "Delete"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
