import { useState } from "react"
import { useNavigate } from "react-router-dom"
import Box from "@mui/material/Box"
import Card from "@mui/material/Card"
import CardContent from "@mui/material/CardContent"
import Typography from "@mui/material/Typography"
import TextField from "@mui/material/TextField"
import Button from "@mui/material/Button"
import CircularProgress from "@mui/material/CircularProgress"
import Alert from "@mui/material/Alert"
import { toast } from "sonner"
import { useAuthStore } from "@/features/auth/authStore"
import { useGetTenant, useUpdateTenant } from "@/lib/api/settings"

export default function DangerZoneTab() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const tenantId = user?.tenant_id
  const { data: tenant, isLoading, isError, error } = useGetTenant(tenantId)
  const updateTenant = useUpdateTenant()
  const [confirmText, setConfirmText] = useState("")
  const slug = (tenant?.slug as string) ?? ""
  const canArchive = confirmText === slug

  const handleArchive = async () => {
    if (!tenantId || !canArchive) return
    try {
      await updateTenant.mutateAsync({ tenantId, data: { status: "archived" } })
      toast.success("Tenant archived. Logging out...")
      setTimeout(() => { logout(); navigate("/login", { replace: true }) }, 1500)
    } catch (err) { toast.error(err instanceof Error ? err.message : "Failed to archive tenant") }
  }

  if (isLoading) return <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}><CircularProgress /></Box>
  if (isError) return <Alert severity="error">{(error as Error)?.message || "Failed to load tenant"}</Alert>

  return (
    <Box sx={{ maxWidth: 480 }}>
      <Card variant="outlined" sx={{ borderColor: "error.main" }}>
        <CardContent sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
            <Typography sx={{ fontSize: "1.25rem" }}>⚠️</Typography>
            <Typography variant="h6" sx={{ fontWeight: 700 }}>Danger Zone</Typography>
          </Box>
          <Typography variant="body2" color="text.secondary">
            Once you archive a tenant, it will be deactivated. All sessions, tools, and associated data
            will be inaccessible. This action cannot be undone.
          </Typography>
          <div>
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>
              Type <Typography component="span" variant="body2" sx={{ fontFamily: "monospace", bgcolor: "grey.100", px: 0.5, borderRadius: 0.5 }}>{slug}</Typography> to confirm:
            </Typography>
            <TextField size="small" value={confirmText} onChange={(e) => setConfirmText(e.target.value)} placeholder={slug} fullWidth />
          </div>
          <Button variant="contained" color="error" onClick={handleArchive} disabled={!canArchive || updateTenant.isPending} sx={{ alignSelf: "flex-start" }}>
            {updateTenant.isPending ? <CircularProgress size={18} /> : "I understand, archive this tenant"}
          </Button>
        </CardContent>
      </Card>
    </Box>
  )
}
