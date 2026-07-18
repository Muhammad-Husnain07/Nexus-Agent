import Typography from "@mui/material/Typography"
import Dashboard from "./Dashboard"

export default function ObservabilityPage() {
  return (
    <div>
      <Typography variant="h5" sx={{ fontWeight: 700, mb: 2 }}>Observability</Typography>
      <Dashboard />
    </div>
  )
}
