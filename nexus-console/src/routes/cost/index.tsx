import Box from "@mui/material/Box"
import Card from "@mui/material/Card"
import CardContent from "@mui/material/CardContent"
import Typography from "@mui/material/Typography"
import Skeleton from "@mui/material/Skeleton"
import { useQuery } from "@tanstack/react-query"
import { ResponsiveContainer, AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts"
import { api } from "@/lib/api"

export default function CostPage() {
  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ["cost", "summary"], queryFn: () => api.get("/cost/summary?days=7").then((r) => r.data),
  })
  const { data: daily, isLoading: dailyLoading } = useQuery({
    queryKey: ["cost", "daily"], queryFn: () => api.get("/cost/daily?days=30").then((r) => r.data),
  })
  const { data: byTenant, isLoading: tenantLoading } = useQuery({
    queryKey: ["cost", "by-tenant"], queryFn: () => api.get("/cost/by-tenant?days=7").then((r) => r.data),
  })

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <Typography variant="h5" sx={{ fontWeight: 700 }}>Cost &amp; Usage</Typography>

      <Box sx={{ display: "grid", gap: 3, gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr 1fr" } }}>
        {[
          { label: "Total Cost", value: `$${((summary as Record<string, number>)?.total_cost_usd ?? 0).toFixed(2)}` },
          { label: "Total Tokens", value: ((summary as Record<string, number>)?.total_tokens ?? 0).toLocaleString() },
          { label: "Total Runs", value: ((summary as Record<string, number>)?.total_runs ?? 0).toLocaleString() },
        ].map((s) => (
          <Card variant="outlined" key={s.label}>
            <CardContent>
              <Typography variant="body2" color="text.secondary">{s.label}</Typography>
              {summaryLoading ? <Skeleton variant="text" width="60%" /> : <Typography variant="h4" sx={{ fontWeight: 700 }}>{s.value}</Typography>}
            </CardContent>
          </Card>
        ))}
      </Box>

      <Card variant="outlined">
        <CardContent>
          <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>Cost Over Time (30 day)</Typography>
          {dailyLoading ? <Skeleton variant="rectangular" height={300} /> : (
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={(daily || []).map((d: Record<string, unknown>) => ({ ...d, date: new Date(d.date as string).toLocaleDateString() }))}>
                <defs><linearGradient id="cost" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="hsl(222.2 47.4% 11.2%)" stopOpacity={0.3} /><stop offset="95%" stopOpacity={0} /></linearGradient></defs>
                <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="date" /><YAxis tickFormatter={(v: number) => `$${v}`} />
                <Tooltip formatter={(v: unknown) => [`$${Number(v).toFixed(2)}`, "Cost"]} />
                <Area type="monotone" dataKey="cost_usd" stroke="hsl(222.2 47.4% 11.2%)" fill="url(#cost)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      <Card variant="outlined">
        <CardContent>
          <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>By Tenant (7 day)</Typography>
          {tenantLoading ? <Skeleton variant="rectangular" height={300} /> : (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={byTenant || []} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" tickFormatter={(v: number) => `$${v.toFixed(0)}`} />
                <YAxis type="category" dataKey="tenant_id" width={200} tickFormatter={(v: string) => v.slice(0, 8) + "..."} />
                <Tooltip formatter={(v: unknown) => [`$${Number(v).toFixed(2)}`, "Cost"]} />
                <Bar dataKey="cost_usd" fill="hsl(222.2 47.4% 11.2%)" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>
    </Box>
  )
}
