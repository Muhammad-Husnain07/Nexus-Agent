import { Box, Typography, Grid, Card, CardContent, Chip, List, ListItem, ListItemText, Button } from "@mui/material";
import { useNavigate } from "react-router-dom";

export default function AdminDashboardPage() {
  const navigate = useNavigate();
  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>Admin Dashboard</Typography>
      <Grid container spacing={3}>
        {[{ label: "Total Tenants", value: "3" }, { label: "Total Users", value: "12" }, { label: "Active API Keys", value: "8" }, { label: "System Health", value: "All OK" }].map((s) => (
          <Grid item xs={12} sm={6} md={3} key={s.label}><Card><CardContent>
            <Typography variant="h5" fontWeight={700}>{s.value}</Typography><Typography variant="caption" color="text.secondary">{s.label}</Typography>
            <Chip label="Active" size="small" color="success" sx={{ mt: 1 }} />
          </CardContent></Card></Grid>
        ))}
      </Grid>
      <Box mt={3} display="flex" gap={2} flexWrap="wrap">
        <Button variant="outlined" onClick={() => navigate("/admin/tenants")}>Manage Tenants</Button>
        <Button variant="outlined" onClick={() => navigate("/admin/users")}>Manage Users</Button>
        <Button variant="outlined" onClick={() => navigate("/admin/api-keys")}>API Keys</Button>
      </Box>
    </Box>
  );
}
