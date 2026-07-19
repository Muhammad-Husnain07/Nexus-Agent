import { Box, Typography, LinearProgress, Alert, Button } from "@mui/material";

interface Props { used: number; limit: number; onSummarize?: () => void; }

export default function ContextWindowIndicator({ used, limit, onSummarize }: Props) {
  const pct = Math.min((used / limit) * 100, 100);
  const warn = pct > 80;

  return (
    <Box sx={{ px: 2, py: 1 }}>
      <Box display="flex" justifyContent="space-between" mb={0.5}>
        <Typography variant="caption" color="text.secondary">Context ({used.toLocaleString()} / {limit.toLocaleString()} tokens)</Typography>
        <Typography variant="caption" color={warn ? "error" : "text.secondary"}>{pct.toFixed(0)}%</Typography>
      </Box>
      <LinearProgress variant="determinate" value={pct} color={warn ? "warning" : "primary"} />
      {warn && (
        <Alert severity="warning" sx={{ mt: 1, py: 0 }}>
          <Typography variant="caption">Approaching context limit</Typography>
          {onSummarize && <Button size="small" onClick={onSummarize} sx={{ ml: 1 }}>Summarize</Button>}
        </Alert>
      )}
    </Box>
  );
}
