import Typography from "@mui/material/Typography"
import SettingsLayout from "./SettingsLayout"

export default function SettingsPage() {
  return (
    <div>
      <Typography variant="h5" sx={{ fontWeight: 700, mb: 2 }}>Settings</Typography>
      <SettingsLayout />
    </div>
  )
}
