import { useState, useEffect } from "react"
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

export default function TenantTab() {
  const user = useAuthStore((s) => s.user)
  const isAdmin = user?.role === "tenant_admin"
  const tenantId = user?.tenant_id
  const { data: tenant, isLoading, isError, error } = useGetTenant(tenantId)
  const updateTenant = useUpdateTenant()

  const [name, setName] = useState("")
  const [maxTokens, setMaxTokens] = useState("")

  useEffect(() => {
    if (tenant) {
      setName(tenant.name ?? "")
      setMaxTokens(String((tenant.settings as Record<string, unknown>)?.max_tokens_per_day ?? ""))
    }
  }, [tenant])

  const handleSave = async () => {
    if (!tenantId) return
    const data: Record<string, unknown> = {}
    if (name !== tenant?.name) data.name = name
    const settings: Record<string, unknown> = {}
    const parsed = parseInt(maxTokens, 10)
    if (!isNaN(parsed)) settings.max_tokens_per_day = parsed
    if (Object.keys(settings).length > 0) data.settings = settings
    if (Object.keys(data).length === 0) return
    try {
      await updateTenant.mutateAsync({ tenantId, data })
      toast.success("Tenant settings updated")
    } catch (err) { toast.error(err instanceof Error ? err.message : "Failed to update tenant") }
  }

  if (isLoading) return <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}><CircularProgress /></Box>
  if (isError) return <Alert severity="error">{(error as Error)?.message || "Failed to load tenant"}</Alert>
  if (!tenant) return <Alert severity="info">Could not load tenant information.</Alert>

  return (
    <Box sx={{ maxWidth: 480, display: "flex", flexDirection: "column", gap: 2 }}>
      <Card variant="outlined">
        <CardContent sx={{ "&:last-child": { pb: 2 } }}>
          <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <div>
              <Typography variant="caption" color="text.secondary">Tenant ID</Typography>
              <Typography variant="caption" sx={{ fontFamily: "monospace", display: "block" }}>{tenant.id}</Typography>
            </div>
            <div>
              <Typography variant="caption" color="text.secondary">Name</Typography>
              {isAdmin ? (
                <TextField size="small" value={name} onChange={(e) => setName(e.target.value)} fullWidth sx={{ mt: 0.5 }} />
              ) : (
                <Typography variant="body1" sx={{ fontWeight: 500 }}>{tenant.name}</Typography>
              )}
            </div>
            <div>
              <Typography variant="caption" color="text.secondary">Slug</Typography>
              <Typography variant="body1" sx={{ fontWeight: 500 }}>{tenant.slug}</Typography>
            </div>
            <div>
              <Typography variant="caption" color="text.secondary">Status</Typography>
              <Typography variant="body1" sx={{ fontWeight: 500 }}>{tenant.status}</Typography>
            </div>
            {isAdmin && (
              <div>
                <Typography variant="caption" color="text.secondary">Max tokens per day</Typography>
                <TextField size="small" type="number" value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)}
                  fullWidth sx={{ mt: 0.5 }} placeholder="e.g. 100000" />
              </div>
            )}
          </Box>
        </CardContent>
      </Card>

      {isAdmin && (
        <Button variant="contained" onClick={handleSave} disabled={updateTenant.isPending} sx={{ alignSelf: "flex-start" }}>
          {updateTenant.isPending ? <CircularProgress size={18} /> : "Save Changes"}
        </Button>
      )}
    </Box>
  )
}
