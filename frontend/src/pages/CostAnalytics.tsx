import { Box, Typography, Grid, Card, CardContent, Button } from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import { AreaChartCard, PieChartCard } from "../components/UI/Charts";

export default function CostAnalyticsPage() {
  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Typography variant="h4" fontWeight={700}>Cost Analytics</Typography>
        <Button startIcon={<DownloadIcon />}>Export</Button>
      </Box>
      <Grid container spacing={3}>
        <Grid item xs={12} md={3}>
          <Card><CardContent><Typography variant="h6">$0.42</Typography><Typography variant="caption" color="text.secondary">Total Cost</Typography></CardContent></Card>
        </Grid>
        <Grid item xs={12} md={3}>
          <Card><CardContent><Typography variant="h6">1,234</Typography><Typography variant="caption" color="text.secondary">Total Tokens</Typography></CardContent></Card>
        </Grid>
        <Grid item xs={12} md={3}>
          <Card><CardContent><Typography variant="h6">56</Typography><Typography variant="caption" color="text.secondary">Total Runs</Typography></CardContent></Card>
        </Grid>
        <Grid item xs={12} md={3}>
          <Card><CardContent><Typography variant="h6">$0.007</Typography><Typography variant="caption" color="text.secondary">Avg Cost / Run</Typography></CardContent></Card>
        </Grid>
      </Grid>
      <Box mt={3}>
        <AreaChartCard title="Daily Cost" data={[]} />
      </Box>
    </Box>
  );
}
