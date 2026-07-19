import { Select, MenuItem, Typography } from "@mui/material";
import BusinessIcon from "@mui/icons-material/Business";
import { useAuthStore } from "../stores/auth-store";

export default function TenantSelector() {
  const { selectedTenantId, selectTenant, user } = useAuthStore();

  if (!user || user.role !== "tenant_admin") return null;

  return (
    <Select
      size="small"
      value={selectedTenantId || ""}
      onChange={(e) => selectTenant(e.target.value)}
      sx={{ minWidth: 140, mr: 1 }}
      renderValue={(v) => (
        <Typography variant="body2" sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
          <BusinessIcon fontSize="small" />
          {v?.slice(0, 8)}...
        </Typography>
      )}
    >
      <MenuItem value={user.tenant_id}>Default Tenant</MenuItem>
    </Select>
  );
}
