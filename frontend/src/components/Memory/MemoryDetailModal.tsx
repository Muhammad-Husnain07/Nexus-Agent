import { Dialog, DialogTitle, DialogContent, DialogActions, Button, Typography, Slider, Box, Chip } from "@mui/material";

interface Props { open: boolean; onClose: () => void; memory: Record<string, unknown> | null; }

export default function MemoryDetailModal({ open, onClose, memory }: Props) {
  if (!memory) return null;
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Memory Detail</DialogTitle>
      <DialogContent>
        <Typography variant="body1" gutterBottom>{memory.content as string}</Typography>
        <Box display="flex" gap={1} mb={2}><Chip label={memory.kind as string} size="small" /></Box>
        <Typography variant="caption" color="text.secondary" display="block">Importance</Typography>
        <Slider value={(memory.importance as number) || 0.5} min={0} max={1} step={0.1} />
        <Typography variant="caption" color="text.secondary">Source: {memory.source_session_id as string}</Typography>
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
    </Dialog>
  );
}
