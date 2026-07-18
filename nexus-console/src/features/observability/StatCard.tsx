import Card from "@mui/material/Card"
import CardContent from "@mui/material/CardContent"
import Typography from "@mui/material/Typography"
import Skeleton from "@mui/material/Skeleton"

interface StatCardProps {
  title: string
  value: string
  loading?: boolean
}

export default function StatCard({ title, value, loading }: StatCardProps) {
  return (
    <Card variant="outlined" sx={{ height: "100%" }}>
      <CardContent>
        <Typography variant="body2" color="text.secondary" gutterBottom>{title}</Typography>
        {loading ? <Skeleton variant="text" width="60%" height={32} /> : (
          <Typography variant="h4" sx={{ fontWeight: 700 }}>{value}</Typography>
        )}
      </CardContent>
    </Card>
  )
}
