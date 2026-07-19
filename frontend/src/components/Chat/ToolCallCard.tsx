import { Card, CardContent, Typography, Chip, Accordion, AccordionSummary, AccordionDetails, Box } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";

interface ToolResult { tool_name: string; status: string; data?: unknown; error?: string; duration_ms?: number; }
interface Props { result: ToolResult; }

export default function ToolCallCard({ result }: Props) {
  return (
    <Card variant="outlined" sx={{ mb: 1 }}>
      <CardContent sx={{ py: 1.5, "&:last-child": { pb: 1.5 } }}>
        <Box display="flex" alignItems="center" gap={1} mb={1}>
          <Typography variant="subtitle2">{result.tool_name}</Typography>
          <Chip label={result.status} size="small" color={result.status === "success" ? "success" : result.status === "error" ? "error" : "default"} />
          {result.duration_ms && <Typography variant="caption" color="text.secondary">{result.duration_ms}ms</Typography>}
        </Box>
        <Accordion>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}><Typography variant="caption">Output</Typography></AccordionSummary>
          <AccordionDetails>
            <Typography variant="body2" component="pre" sx={{ fontFamily: "monospace", fontSize: 12, whiteSpace: "pre-wrap" }}>
              {JSON.stringify(result.data || result.error, null, 2)}
            </Typography>
          </AccordionDetails>
        </Accordion>
      </CardContent>
    </Card>
  );
}
