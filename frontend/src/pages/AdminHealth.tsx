import { Box, Typography, Grid, Card, CardContent, Chip, Accordion, AccordionSummary, AccordionDetails, LinearProgress } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";

export default function AdminHealthPage() {
  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>System Health</Typography>
      <Grid container spacing={2} mb={3}>
        {[
          { label: "Database", status: "Healthy", color: "success" as const },
          { label: "Redis", status: "Healthy", color: "success" as const },
          { label: "LLM Provider", status: "Connected", color: "success" as const },
          { label: "Queue Depth", status: "0", color: "default" as const },
        ].map((s) => (
          <Grid item xs={6} sm={3} key={s.label}>
            <Card><CardContent><Typography variant="subtitle2">{s.label}</Typography>
              <Chip label={s.status} size="small" color={s.color} sx={{ mt: 1 }} /></CardContent></Card>
          </Grid>
        ))}
      </Grid>
      <Accordion><AccordionSummary expandIcon={<ExpandMoreIcon />}><Typography>Version & Changelog</Typography></AccordionSummary>
        <AccordionDetails><Typography variant="body2" color="text.secondary">v0.1.0 — Initial release</Typography></AccordionDetails>
      </Accordion>
    </Box>
  );
}
