import Box from "@mui/material/Box"
import Card from "@mui/material/Card"
import CardContent from "@mui/material/CardContent"
import Typography from "@mui/material/Typography"
import { DollarSign, Hash, Activity, Gauge } from "lucide-react"
import { useGetDashboardMetrics } from "@/lib/api/metrics"
import StatCard from "./StatCard"
import CostChart from "./CostChart"
import ToolUsageChart from "./ToolUsageChart"
import RecentRunsTable from "./RecentRunsTable"

function formatCurrency(n: number): string { return `$${n.toFixed(2)}` }
function formatCompact(n: number): string { return n.toLocaleString() }

export default function Dashboard() {
  const { data: metrics, isLoading: metricsLoading } = useGetDashboardMetrics(7)

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr", lg: "1fr 1fr 1fr 1fr" }, gap: 2 }}>
        <StatCard title="Total Cost" value={metricsLoading ? "\u2014" : formatCurrency(metrics?.total_cost_usd ?? 0)} icon={DollarSign} loading={metricsLoading} />
        <StatCard title="Total Tokens" value={metricsLoading ? "\u2014" : formatCompact(metrics?.total_tokens ?? 0)} icon={Hash} loading={metricsLoading} />
        <StatCard title="Total Runs" value={metricsLoading ? "\u2014" : formatCompact(metrics?.total_runs ?? 0)} icon={Activity} loading={metricsLoading} />
        <StatCard title="Avg Latency" value="\u2014" icon={Gauge} />
      </Box>

      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", lg: "1fr 1fr" }, gap: 2 }}>
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
