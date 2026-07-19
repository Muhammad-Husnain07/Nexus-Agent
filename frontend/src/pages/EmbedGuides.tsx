import { Box, Typography, Accordion, AccordionSummary, AccordionDetails, Paper, IconButton, Alert } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";

const snippets = {
  html: '<script src="https://your-domain.com/embed.js" data-widget-id="YOUR_WIDGET_ID"></script>',
  react: 'import { EmbeddedChat } from "@nexus/embed";\n<EmbeddedChat widgetId="YOUR_WIDGET_ID" />',
};

export default function EmbedGuidesPage() {
  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>Integration Guides</Typography>
      {Object.entries(snippets).map(([lang, code]) => (
        <Accordion key={lang}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}><Typography textTransform="capitalize">{lang}</Typography></AccordionSummary>
          <AccordionDetails>
            <Paper sx={{ p: 2, position: "relative" }}>
              <pre style={{ margin: 0, fontSize: 13 }}>{code}</pre>
              <IconButton size="small" sx={{ position: "absolute", top: 8, right: 8 }} onClick={() => navigator.clipboard.writeText(code)}>
                <ContentCopyIcon fontSize="small" /></IconButton>
            </Paper>
          </AccordionDetails>
        </Accordion>
      ))}
      <Alert severity="info" sx={{ mt: 2 }}>See docs for detailed platform-specific guides (WordPress, Shopify, etc.)</Alert>
    </Box>
  );
}
