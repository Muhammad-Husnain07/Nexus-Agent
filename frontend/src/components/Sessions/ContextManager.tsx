import { Box, Typography, LinearProgress, Switch, FormControlLabel, Button, List, ListItem, ListItemText, ListItemIcon } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";

interface Props { totalTokens: number; maxTokens: number; onSummarize?: () => void; }

export default function ContextManager({ totalTokens, maxTokens, onSummarize }: Props) {
  const pct = Math.min((totalTokens / maxTokens) * 100, 100);
  return (
    <Box sx={{ p: 2 }}>
      <Typography variant="subtitle2" gutterBottom>Context Window</Typography>
      <Box display="flex" justifyContent="space-between" mb={0.5}>
        <Typography variant="caption">{totalTokens.toLocaleString()} / {maxTokens.toLocaleString()} tokens</Typography>
        <Typography variant="caption" color={pct > 80 ? "error" : "text.secondary"}>{pct.toFixed(0)}%</Typography>
      </Box>
      <LinearProgress variant="determinate" value={pct} color={pct > 80 ? "warning" : "primary"} sx={{ mb: 2 }} />
      {onSummarize && <Button size="small" variant="outlined" onClick={onSummarize} fullWidth>Summarize</Button>}
    </Box>
  );
}
