import { Card, CardContent, CardHeader, Skeleton } from "@mui/material";
import { LineChart, BarChart, PieChart, AreaChart, Line, Bar, Pie, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";

interface ChartProps { title?: string; data: Record<string, unknown>[]; loading?: boolean; height?: number; }

export function LineChartCard({ title, data, loading, height = 300 }: ChartProps) {
  return (
    <Card>
      {title && <CardHeader title={title} />}
      <CardContent>
        {loading ? <Skeleton variant="rectangular" height={height} /> : (
          <ResponsiveContainer width="100%" height={height}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" /><YAxis /><Tooltip /><Legend />
              <Line type="monotone" dataKey="value" stroke="#1976d2" strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}

export function BarChartCard({ title, data, loading, height = 300 }: ChartProps) {
  return (
    <Card>
      {title && <CardHeader title={title} />}
      <CardContent>
        {loading ? <Skeleton variant="rectangular" height={height} /> : (
          <ResponsiveContainer width="100%" height={height}>
            <BarChart data={data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" /><YAxis /><Tooltip /><Legend />
              <Bar dataKey="value" fill="#1976d2" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}

export function PieChartCard({ title, data, loading, height = 300 }: ChartProps) {
  return (
    <Card>
      {title && <CardHeader title={title} />}
      <CardContent>
        {loading ? <Skeleton variant="rectangular" height={height} /> : (
          <ResponsiveContainer width="100%" height={height}>
            <PieChart>
              <Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={100} fill="#1976d2" label />
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}

export function AreaChartCard({ title, data, loading, height = 300 }: ChartProps) {
  return (
    <Card>
      {title && <CardHeader title={title} />}
      <CardContent>
        {loading ? <Skeleton variant="rectangular" height={height} /> : (
          <ResponsiveContainer width="100%" height={height}>
            <AreaChart data={data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" /><YAxis /><Tooltip /><Legend />
              <Area type="monotone" dataKey="value" stroke="#1976d2" fill="#1976d2" fillOpacity={0.1} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
