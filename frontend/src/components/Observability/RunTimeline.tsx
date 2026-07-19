import { Timeline, TimelineItem, TimelineSeparator, TimelineConnector, TimelineContent, TimelineDot } from "@mui/lab";
import { Typography } from "@mui/material";

interface RunEvent { node: string; status: string; started_at: string; }
interface Props { events: RunEvent[]; }

export default function RunTimeline({ events }: Props) {
  return (
    <Timeline>
      {events.map((e, i) => (
        <TimelineItem key={i}>
          <TimelineSeparator><TimelineDot color={e.status === "success" ? "success" : e.status === "error" ? "error" : "grey"} />{i < events.length - 1 && <TimelineConnector />}</TimelineSeparator>
          <TimelineContent><Typography variant="body2">{e.node}</Typography><Typography variant="caption" color="text.secondary">{e.status}</Typography></TimelineContent>
        </TimelineItem>
      ))}
    </Timeline>
  );
}
