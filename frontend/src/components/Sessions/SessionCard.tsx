import { Card, CardContent, Typography, Chip, Box, IconButton } from "@mui/material";
import ArchiveIcon from "@mui/icons-material/Archive";
import DeleteIcon from "@mui/icons-material/Delete";
import type { Session } from "../../types/session";

interface Props { session: Session; onArchive: () => void; onDelete: () => void; }

export default function SessionCard({ session, onArchive, onDelete }: Props) {
  return (
    <Card variant="outlined" sx={{ mb: 1, cursor: "pointer" }}>
      <CardContent sx={{ py: 1.5, "&:last-child": { pb: 1.5 } }}>
        <Box display="flex" justifyContent="space-between" alignItems="center">
          <Box flex={1}>
            <Typography variant="subtitle2">{session.title}</Typography>
            <Chip label={session.status} size="small" color={session.status === "active" ? "success" : "default"} sx={{ mr: 1 }} />
            <Typography variant="caption" color="text.secondary">{new Date(session.created_at).toLocaleDateString()}</Typography>
          </Box>
          <Box><IconButton size="small" onClick={onArchive}><ArchiveIcon fontSize="small" /></IconButton><IconButton size="small" onClick={onDelete}><DeleteIcon fontSize="small" /></IconButton></Box>
        </Box>
      </CardContent>
    </Card>
  );
}
