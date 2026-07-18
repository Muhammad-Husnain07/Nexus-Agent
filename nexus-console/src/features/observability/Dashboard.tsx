import Box from "@mui/material/Box"
import Card from "@mui/material/Card"
import CardContent from "@mui/material/CardContent"
import Typography from "@mui/material/Typography"
import { useGetDashboardMetrics } from "@/lib/api/metrics"
import StatCard from "./StatCard"
import CostChart from "./CostChart"
import ToolUsageChart from "./ToolUsageChart"
import RecentRunsTable from "./RecentRunsTable"

export default function Dashboard() {
  const { data: metrics, isLoading } = useGetDashboardMetrics(7)

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <Box sx={{ display: "grid", gap: 3, gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr", md: "1fr 1fr 1fr 1fr" } }}>
        <StatCard title="Total Cost" value={`$${(metrics?.total_cost_usd ?? 0).toFixed(2)}`} loading={isLoading} />
        <StatCard title="Total Tokens" value={(metrics?.total_tokens ?? 0).toLocaleString()} loading={isLoading} />
        <StatCard title="Total Runs" value={(metrics?.total_runs ?? 0).toLocaleString()} loading={isLoading} />
        <StatCard title="Avg Latency" value="\u2014" loading={false} />
      </Box>

      <Box sx={{ display: "grid", gap: 3, gridTemplateColumns: { xs: "1fr", lg: "2fr 1fr" } }}>
        <Card variant="outlined">
          <CardContent>
            <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>Cost Over Time (30 days)</Typography>
            <CostChart />
          </CardContent>
        </Card>
        <Card variant="outlined">
          <CardContent>
            <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>Tool Usage</Typography>
            <ToolUsageChart />
          </CardContent>
        </Card>
      </Box>

      <RecentRunsTable />
    </Box>
  )
}
