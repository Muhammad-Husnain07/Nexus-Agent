import { Card, CardContent, CardHeader, Box } from "@mui/material";
import { LineChart, Line, BarChart, Bar, PieChart, Pie, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";

interface ChartProps { title?: string; data: Record<string, unknown>[]; loading?: boolean; height?: number; }

export function DailyCostChart({ data }: { data: Record<string, unknown>[] }) {
  return (<Card><CardHeader title="Daily Cost" /><CardContent><ResponsiveContainer width="100%" height={300}>
    <AreaChart data={data}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="date" /><YAxis /><Tooltip />
      <Area type="monotone" dataKey="cost" stroke="#1976d2" fill="#1976d2" fillOpacity={0.1} /></AreaChart></ResponsiveContainer></CardContent></Card>);
}

export function CostByModelChart({ data }: { data: Record<string, unknown>[] }) {
  return (<Card><CardHeader title="Cost by Model" /><CardContent><ResponsiveContainer width="100%" height={300}>
    <PieChart><Pie data={data} dataKey="cost" nameKey="model" cx="50%" cy="50%" outerRadius={100} fill="#1976d2" label /></PieChart></ResponsiveContainer></CardContent></Card>);
}

export function TokenUsageChart({ data }: { data: Record<string, unknown>[] }) {
  return (<Card><CardHeader title="Token Usage" /><CardContent><ResponsiveContainer width="100%" height={300}>
    <BarChart data={data}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="date" /><YAxis /><Tooltip />
      <Bar dataKey="prompt" stackId="a" fill="#1976d2" /><Bar dataKey="completion" stackId="a" fill="#82ca9d" /></BarChart></ResponsiveContainer></CardContent></Card>);
}
