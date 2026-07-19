import { Card, CardContent, Typography, Accordion, AccordionSummary, AccordionDetails, Switch, FormControlLabel, TextField, Box } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";

export default function EscalationRules() {
  return (
    <Card><CardContent>
      <Typography variant="h6" gutterBottom>Escalation Rules</Typography>
      <Accordion><AccordionSummary expandIcon={<ExpandMoreIcon />}>By Tool (Trusted Tools)</AccordionSummary>
        <AccordionDetails><FormControlLabel control={<Switch />} label="Auto-approve low risk tools" /></AccordionDetails>
      </Accordion>
      <Accordion><AccordionSummary expandIcon={<ExpandMoreIcon />}>By Risk Level</AccordionSummary>
        <AccordionDetails><FormControlLabel control={<Switch defaultChecked />} label="Auto-approve low risk" /></AccordionDetails>
      </Accordion>
      <Accordion><AccordionSummary expandIcon={<ExpandMoreIcon />}>By Time of Day</AccordionSummary>
        <AccordionDetails><TextField size="small" label="During hours" /></AccordionDetails>
      </Accordion>
    </CardContent></Card>
  );
}
