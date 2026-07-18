import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts"
import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import Alert from "@mui/material/Alert"
import Skeleton from "@/components/skeletons/Skeleton"
import { useGetToolUsage } from "@/lib/api/metrics"

export default function ToolUsageChart() {
  const { data, isLoading, isError, error } = useGetToolUsage(30)

  if (isLoading) return <Skeleton sx={{ height: 280, borderRadius: 1 }} />
  if (isError) return <Alert severity="error">{(error as Error)?.message || "Failed to load tool usage data"}</Alert>
  if (!data || data.length === 0) {
    return (
      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "center", height: 280, color: "text.secondary" }}>
        <Typography variant="body2">No tool usage data available for this period.</Typography>
      </Box>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={data} layout="vertical" margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(214.3 31.8% 91.4%)" horizontal={false} />
        <XAxis type="number" tick={{ fontSize: 12 }} stroke="hsl(215.4 16.3% 46.9%)" />
        <YAxis type="category" dataKey="tool_name" tick={{ fontSize: 12 }} stroke="hsl(215.4 16.3% 46.9%)" width={120} />
        <Tooltip formatter={(value: unknown) => [Number(value), "Executions"]}
          contentStyle={{ fontSize: 13, borderRadius: 6, border: "1px solid hsl(214.3 31.8% 91.4%)" }} />
        <Bar dataKey="execution_count" fill="hsl(222.2 47.4% 11.2%)" radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}
