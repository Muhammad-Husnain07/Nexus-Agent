import { Box, TextField, Button, Card, CardContent, Typography, LinearProgress, Grid } from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";

export default function LoadTester() {
  return (
    <Box>
      <Box display="flex" gap={2} mb={2}>
        <TextField size="small" label="Concurrent Requests" type="number" defaultValue={10} sx={{ width: 160 }} />
        <TextField size="small" label="Duration (s)" type="number" defaultValue={30} sx={{ width: 140 }} />
        <Button variant="contained" startIcon={<PlayArrowIcon />}>Start</Button>
      </Box>
      <Grid container spacing={2}>
        {[
          { label: "Requests/s", value: "0" },
          { label: "Avg Latency", value: "-" },
          { label: "P99 Latency", value: "-" },
          { label: "Errors", value: "0" },
        ].map((m) => (
          <Grid item xs={3} key={m.label}><Card><CardContent sx={{ textAlign: "center", py: 1.5 }}>
            <Typography variant="h6">{m.value}</Typography><Typography variant="caption" color="text.secondary">{m.label}</Typography>
          </CardContent></Card></Grid>
        ))}
      </Grid>
      <Box mt={2}><LinearProgress variant="determinate" value={0} /></Box>
    </Box>
  );
}
