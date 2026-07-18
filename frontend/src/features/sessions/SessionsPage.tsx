import Typography from "@mui/material/Typography"
import SessionsList from "./SessionsList"

export default function SessionsPage() {
  return (
    <div>
      <Typography variant="h5" sx={{ fontWeight: 700, mb: 2 }}>Sessions</Typography>
      <SessionsList />
    </div>
  )
}
