import { useState } from "react"
import Box from "@mui/material/Box"
import Card from "@mui/material/Card"
import CardContent from "@mui/material/CardContent"
import Typography from "@mui/material/Typography"
import TextField from "@mui/material/TextField"
import Button from "@mui/material/Button"
import Avatar from "@mui/material/Avatar"
import CircularProgress from "@mui/material/CircularProgress"
import { useSnackbar } from "notistack"
import { useAuthStore } from "@/features/auth/authStore"
import { useUpdateUser } from "@/lib/api/settings"

export default function ProfileTab() {
  const user = useAuthStore((s) => s.user)
  const isAdmin = user?.role === "tenant_admin"
  const [editing, setEditing] = useState(false)
  const [email, setEmail] = useState(user?.email ?? "")
  const updateUser = useUpdateUser()
  const { enqueueSnackbar } = useSnackbar()

  const handleSave = async () => {
    if (!user?.id) return
    try { await updateUser.mutateAsync({ userId: user.id, data: { email } }); enqueueSnackbar("Profile updated", { variant: "success" }); setEditing(false) }
    catch (err) { enqueueSnackbar(err instanceof Error ? err.message : "Failed", { variant: "error" }) }
  }

  return (
    <Box sx={{ maxWidth: 480, display: "flex", flexDirection: "column", gap: 2 }}>
      <Card variant="outlined">
        <CardContent sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
            <Avatar sx={{ width: 56, height: 56, bgcolor: "primary.main", fontSize: 24 }}>
              {user?.email?.charAt(0).toUpperCase() || "?"}
            </Avatar>
            <Box>
              <Typography variant="body1" sx={{ fontWeight: 600 }}>{user?.email}</Typography>
              <Typography variant="caption" color="text.secondary">{user?.role}</Typography>
            </Box>
          </Box>
          {editing ? (
            <TextField label="Email" size="small" value={email} onChange={(e) => setEmail(e.target.value)} fullWidth />
          ) : (
            <TextField label="Email" size="small" value={user?.email || ""} disabled fullWidth />
          )}
          <Typography variant="caption" color="text.secondary">User ID: {user?.id}</Typography>
        </CardContent>
      </Card>
      {isAdmin && (
        <Box sx={{ display: "flex", gap: 1 }}>
          {editing ? (
            <>
              <Button variant="contained" onClick={handleSave} disabled={updateUser.isPending}>
                {updateUser.isPending ? <CircularProgress size={18} /> : "Save"}
              </Button>
              <Button variant="outlined" onClick={() => { setEditing(false); setEmail(user?.email ?? "") }}>Cancel</Button>
            </>
          ) : (
            <Button variant="outlined" onClick={() => setEditing(true)}>Edit Profile</Button>
          )}
        </Box>
      )}
    </Box>
  )
}
