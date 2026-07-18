import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts"
import Box from "@mui/material/Box"
import Typography from "@mui/material/Typography"
import Alert from "@mui/material/Alert"
import Skeleton from "@/components/skeletons/Skeleton"
import { useGetCostTrend } from "@/lib/api/metrics"

export default function CostChart() {
  const { data, isLoading, isError, error } = useGetCostTrend(30)

  if (isLoading) return <Skeleton sx={{ height: 280, borderRadius: 1 }} />
  if (isError) return <Alert severity="error">{(error as Error)?.message || "Failed to load cost data"}</Alert>
  if (!data || data.length === 0) {
    return (
      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "center", height: 280, color: "text.secondary" }}>
        <Typography variant="body2">No cost data available for this period.</Typography>
      </Box>
    )
  }

  const formatted = data.map((d) => ({
    ...d, date: new Date(d.date).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
  }))

  return (
    <ResponsiveContainer width="100%" height={280}>
      <AreaChart data={formatted} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
        <defs>
          <linearGradient id="costGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="hsl(222.2 47.4% 11.2%)" stopOpacity={0.3} />
            <stop offset="95%" stopColor="hsl(222.2 47.4% 11.2%)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(214.3 31.8% 91.4%)" />
        <XAxis dataKey="date" tick={{ fontSize: 12 }} stroke="hsl(215.4 16.3% 46.9%)" />
        <YAxis tick={{ fontSize: 12 }} stroke="hsl(215.4 16.3% 46.9%)" tickFormatter={(v: number) => `$${v}`} />
        <Tooltip formatter={(value: unknown) => [`$${Number(value).toFixed(2)}`, "Cost"]}
          contentStyle={{ fontSize: 13, borderRadius: 6, border: "1px solid hsl(214.3 31.8% 91.4%)" }} />
        <Area type="monotone" dataKey="cost_usd" stroke="hsl(222.2 47.4% 11.2%)" fill="url(#costGradient)" strokeWidth={2} />
      </AreaChart>
    </ResponsiveContainer>
  )
}
