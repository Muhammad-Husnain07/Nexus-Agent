import { useState } from "react"
import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import Button from "@mui/material/Button"
import TextField from "@mui/material/TextField"
import Chip from "@mui/material/Chip"
import Dialog from "@mui/material/Dialog"
import DialogTitle from "@mui/material/DialogTitle"
import DialogContent from "@mui/material/DialogContent"
import DialogActions from "@mui/material/DialogActions"
import Skeleton from "@mui/material/Skeleton"
import { DataGrid, type GridColDef, type GridRenderCellParams } from "@mui/x-data-grid"
import AddIcon from "@mui/icons-material/Add"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useSnackbar } from "notistack"
import { api } from "@/lib/api"

interface Tenant {
  id: string; name: string; slug: string; status: string; created_at: string
}

export default function TenantsPage() {
  const { enqueueSnackbar } = useSnackbar()
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState("")
  const [slug, setSlug] = useState("")

  const { data, isLoading } = useQuery<Tenant[]>({
    queryKey: ["admin", "tenants"],
    queryFn: () => api.get("/admin/tenants").then((r) => r.data),
  })

  const createMutation = useMutation({
    mutationFn: (body: { name: string; slug: string }) => api.post("/admin/tenants", body),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["admin", "tenants"] }); enqueueSnackbar("Tenant created", { variant: "success" }); setCreateOpen(false) },
    onError: (err: Error) => enqueueSnackbar(err.message, { variant: "error" }),
  })

  const columns: GridColDef[] = [
    { field: "name", headerName: "Name", flex: 1 },
    { field: "slug", headerName: "Slug", width: 150 },
    { field: "status", headerName: "Status", width: 120,
      renderCell: (params: GridRenderCellParams) => <Chip label={params.value} size="small" color={params.value === "active" ? "success" : "default"} />,
    },
    { field: "created_at", headerName: "Created", width: 200,
      renderCell: (params: GridRenderCellParams) => new Date(params.value as string).toLocaleString(),
    },
  ]

  return (
    <Box>
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 2 }}>
        <Typography variant="h5" sx={{ fontWeight: 700 }}>Tenants &amp; Users</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>Create Tenant</Button>
      </Box>

      {isLoading ? <Skeleton variant="rectangular" height={400} /> : (
        <DataGrid rows={data || []} columns={columns} getRowId={(r) => r.id}
          autoHeight pageSizeOptions={[10, 25]} disableRowSelectionOnClick
          sx={{ "& .MuiDataGrid-cell:focus": { outline: "none" } }} />
      )}

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Create Tenant</DialogTitle>
        <DialogContent sx={{ pt: "8px !important", display: "flex", flexDirection: "column", gap: 2 }}>
          <TextField label="Name" size="small" value={name} onChange={(e) => setName(e.target.value)} fullWidth />
          <TextField label="Slug" size="small" value={slug} onChange={(e) => setSlug(e.target.value)} fullWidth required helperText="URL-safe unique identifier" />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={() => createMutation.mutate({ name, slug })} disabled={!slug || createMutation.isPending}>
            {createMutation.isPending ? "Creating..." : "Create"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
