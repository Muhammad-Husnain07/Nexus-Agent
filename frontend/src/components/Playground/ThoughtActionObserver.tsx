import { Timeline, TimelineItem, TimelineSeparator, TimelineConnector, TimelineContent, TimelineDot } from "@mui/lab";
import { Box, Button, Typography } from "@mui/material";

interface Step { action: string; thought: string; observation: string; }
interface Props { steps: Step[]; }

export default function ThoughtActionObserver({ steps }: Props) {
  return (
    <Box>
      <Box display="flex" gap={1} mb={2}><Button size="small">Prev</Button><Button size="small">Next</Button></Box>
      <Timeline>
        {steps.map((s, i) => (
          <TimelineItem key={i}>
            <TimelineSeparator><TimelineDot /><TimelineConnector /></TimelineSeparator>
            <TimelineContent>
              <Typography variant="body2" fontWeight={600}>Thought: {s.thought}</Typography>
              <Typography variant="body2">Action: {s.action}</Typography>
              <Typography variant="caption" color="text.secondary">Observation: {s.observation}</Typography>
            </TimelineContent>
          </TimelineItem>
        ))}
      </Timeline>
    </Box>
  );
}
