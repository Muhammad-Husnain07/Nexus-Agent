import { Card, CardContent, Typography, Chip, LinearProgress, Box, IconButton } from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import VisibilityIcon from "@mui/icons-material/Visibility";

interface MemoryItem { id: string; content: string; kind: string; importance: number; created_at: string; }
interface Props { memory: MemoryItem; onView: () => void; onDelete: () => void; }

export default function MemoryCard({ memory, onView, onDelete }: Props) {
  return (
    <Card variant="outlined" sx={{ mb: 1 }}>
      <CardContent sx={{ py: 1.5, "&:last-child": { pb: 1.5 } }}>
        <Box display="flex" justifyContent="space-between" alignItems="center">
          <Box flex={1}>
            <Typography variant="body2" sx={{ mb: 0.5 }}>{memory.content?.slice(0, 120)}...</Typography>
            <Box display="flex" gap={1} alignItems="center">
              <Chip label={memory.kind} size="small" />
              <LinearProgress variant="determinate" value={memory.importance * 100} sx={{ width: 60, height: 6, borderRadius: 3 }} />
            </Box>
          </Box>
          <Box>
            <IconButton size="small" onClick={onView}><VisibilityIcon fontSize="small" /></IconButton>
            <IconButton size="small" onClick={onDelete}><DeleteIcon fontSize="small" /></IconButton>
          </Box>
        </Box>
      </CardContent>
    </Card>
  );
}
