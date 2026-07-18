import Card from "@mui/material/Card"
import CardContent from "@mui/material/CardContent"
import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import CircularProgress from "@mui/material/CircularProgress"
import type { LucideIcon } from "lucide-react"

interface StatCardProps {
  title: string
  value: string
  icon: LucideIcon
  loading?: boolean
}

export default function StatCard({ title, value, icon: Icon, loading }: StatCardProps) {
  return (
    <Card variant="outlined">
      <CardContent>
        <Box sx={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="body2" color="text.secondary">{title}</Typography>
            {loading ? (
              <Box sx={{ mt: 0.5 }}><CircularProgress size={18} /></Box>
            ) : (
              <Typography variant="h5" sx={{ fontWeight: 700, mt: 0.5 }}>{value}</Typography>
            )}
          </Box>
          <Box sx={{ color: "text.disabled", flexShrink: 0, ml: 2 }}>
            <Icon size={24} />
          </Box>
        </Box>
      </CardContent>
    </Card>
  )
}
