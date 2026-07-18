import Typography from "@mui/material/Typography"
import ToolsList from "./ToolsList"

export default function ToolsPage() {
  return (
    <div>
      <Typography variant="h5" sx={{ fontWeight: 700, mb: 2 }}>Tools</Typography>
      <ToolsList />
    </div>
  )
}
