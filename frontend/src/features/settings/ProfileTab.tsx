import { useState } from "react"
import Box from "@mui/material/Box"
import Card from "@mui/material/Card"
import CardContent from "@mui/material/CardContent"
import Typography from "@mui/material/Typography"
import TextField from "@mui/material/TextField"
import Button from "@mui/material/Button"
import CircularProgress from "@mui/material/CircularProgress"
import { toast } from "sonner"
import { useAuthStore } from "@/features/auth/authStore"
import { useUpdateUser } from "@/lib/api/settings"

export default function ProfileTab() {
  const user = useAuthStore((s) => s.user)
  const isAdmin = user?.role === "tenant_admin"
  const [editing, setEditing] = useState(false)
  const [email, setEmail] = useState(user?.email ?? "")
  const updateUser = useUpdateUser()

  const handleSave = async () => {
    if (!user?.id) return
    try {
      await updateUser.mutateAsync({ userId: user.id, data: { email } })
      toast.success("Profile updated"); setEditing(false)
    } catch (err) { toast.error(err instanceof Error ? err.message : "Failed to update profile") }
  }

  return (
    <Box sx={{ maxWidth: 480, display: "flex", flexDirection: "column", gap: 2 }}>
      <Card variant="outlined">
        <CardContent sx={{ "&:last-child": { pb: 2 } }}>
          <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <div>
              <Typography variant="caption" color="text.secondary">Email</Typography>
              {editing ? (
                <TextField size="small" value={email} onChange={(e) => setEmail(e.target.value)} fullWidth sx={{ mt: 0.5 }} />
              ) : (
                <Typography variant="body1" sx={{ fontWeight: 500 }}>{user?.email}</Typography>
              )}
            </div>
            <div>
              <Typography variant="caption" color="text.secondary">Role</Typography>
              <Typography variant="body1" sx={{ fontWeight: 500 }}>{user?.role}</Typography>
            </div>
            <div>
              <Typography variant="caption" color="text.secondary">User ID</Typography>
              <Typography variant="caption" sx={{ fontFamily: "monospace", display: "block" }}>{user?.id}</Typography>
            </div>
            <div>
              <Typography variant="caption" color="text.secondary">Tenant ID</Typography>
              <Typography variant="caption" sx={{ fontFamily: "monospace", display: "block" }}>{user?.tenant_id}</Typography>
            </div>
          </Box>
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
