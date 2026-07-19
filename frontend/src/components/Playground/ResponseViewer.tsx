import { Box, Tabs, Tab, Typography, Accordion, AccordionSummary, AccordionDetails } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { useState } from "react";

interface Props { response?: Record<string, unknown>; loading?: boolean; }

export default function ResponseViewer({ response, loading }: Props) {
  const [tab, setTab] = useState(0);
  if (loading) return <Box sx={{ p: 2, bgcolor: "grey.100", borderRadius: 1, minHeight: 200 }}><Typography color="text.secondary">Loading...</Typography></Box>;
  return (
    <Box>
      <Tabs value={tab} onChange={(_, v) => setTab(v)}><Tab label="Pretty" /><Tab label="Raw" /><Tab label="Headers" /></Tabs>
      <Box sx={{ p: 2, bgcolor: "grey.100", borderRadius: 1, minHeight: 200, fontFamily: "monospace", fontSize: 13 }}>
        {response ? <Accordion><AccordionSummary expandIcon={<ExpandMoreIcon />}>Response</AccordionSummary>
          <AccordionDetails><pre>{JSON.stringify(response, null, 2)}</pre></AccordionDetails></Accordion>
          : <Typography color="text.secondary">Send a request to see the response</Typography>}
      </Box>
    </Box>
  );
}
