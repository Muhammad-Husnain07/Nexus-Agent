import { useState } from "react";
import { Box, List, ListItem, ListItemButton, ListItemText, TextField, Button, Typography, IconButton, ListSubheader, Badge, InputAdornment } from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import SearchIcon from "@mui/icons-material/Search";

interface Session { id: string; title: string; status: string; message_count?: number; created_at: string; }
interface Props { sessions: Session[]; activeId?: string; onSelect: (id: string) => void; onNew: () => void; }

export default function SessionsSidebar({ sessions, activeId, onSelect, onNew }: Props) {
  const [search, setSearch] = useState("");
  const filtered = sessions.filter((s) => s.title.toLowerCase().includes(search.toLowerCase()));

  return (
    <Box sx={{ width: 280, borderRight: 1, borderColor: "divider", height: "100%", display: "flex", flexDirection: "column" }}>
      <Box sx={{ p: 2, borderBottom: 1, borderColor: "divider" }}>
        <Button fullWidth variant="contained" startIcon={<AddIcon />} onClick={onNew}>New Chat</Button>
        <TextField size="small" placeholder="Search sessions..." value={search} onChange={(e) => setSearch(e.target.value)} fullWidth sx={{ mt: 1 }}
          InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }} />
      </Box>
      <List sx={{ flex: 1, overflow: "auto" }}>
        {filtered.map((s) => (
          <ListItem key={s.id} disablePadding secondaryAction={
            <Badge badgeContent={0} color="error" />
          }>
            <ListItemButton selected={s.id === activeId} onClick={() => onSelect(s.id)} dense>
              <ListItemText primary={s.title} secondary={`${s.message_count || 0} msgs`} />
            </ListItemButton>
          </ListItem>
        ))}
        {filtered.length === 0 && <Typography variant="body2" color="text.secondary" sx={{ p: 2, textAlign: "center" }}>No sessions</Typography>}
      </List>
    </Box>
  );
}
