import { Card, CardContent, Typography, Grid, Box } from "@mui/material";

export default function PerformanceMetrics() {
  return (
    <Grid container spacing={2}>
      {[
        { label: "P50 Latency", value: "320ms" },
        { label: "P95 Latency", value: "1.2s" },
        { label: "P99 Latency", value: "2.8s" },
        { label: "Success Rate", value: "98.5%" },
        { label: "Throughput", value: "14 runs/hr" },
      ].map((m) => (
        <Grid item xs={6} sm={4} key={m.label}>
          <Card><CardContent sx={{ textAlign: "center", py: 2 }}>
            <Typography variant="h5" fontWeight={700}>{m.value}</Typography>
            <Typography variant="caption" color="text.secondary">{m.label}</Typography>
          </CardContent></Card>
        </Grid>
      ))}
    </Grid>
  );
}
