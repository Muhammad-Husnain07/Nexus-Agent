import { Card, CardContent, CardActions, Typography, Chip, IconButton, Switch, Box, LinearProgress } from "@mui/material";
import EditIcon from "@mui/icons-material/Edit";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import type { ToolDefinition } from "../../types/tool";

interface Props { tool: ToolDefinition; onEdit: () => void; onTest: () => void; }

export default function ToolCard({ tool, onEdit, onTest }: Props) {
  return (
    <Card variant="outlined" sx={{ "&:hover": { boxShadow: 2 } }}>
      <CardContent>
        <Box display="flex" justifyContent="space-between" alignItems="center">
          <Typography variant="subtitle2">{tool.name}</Typography>
          <Chip label={tool.risk_level} size="small" color={tool.risk_level === "low" ? "success" : tool.risk_level === "medium" ? "warning" : "error"} />
        </Box>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ my: 0.5 }}>{tool.description?.slice(0, 80)}</Typography>
        <Box display="flex" gap={0.5}><Chip label={tool.category} size="small" variant="outlined" /><Chip label={tool.http_method} size="small" color="primary" variant="outlined" /></Box>
      </CardContent>
      <CardActions><IconButton size="small" onClick={onEdit}><EditIcon fontSize="small" /></IconButton><IconButton size="small" onClick={onTest}><PlayArrowIcon fontSize="small" /></IconButton><Switch size="small" checked={tool.enabled} sx={{ ml: "auto" }} /></CardActions>
    </Card>
  );
}
