import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Dialog, Autocomplete, TextField, Box, Typography, ListItemIcon, ListItemText } from "@mui/material";
import SearchIcon from "@mui/icons-material/Search";

const actions = [
  { label: "Go to Dashboard", path: "/dashboard", icon: "Dashboard" },
  { label: "New Chat", path: "/chat", icon: "Chat" },
  { label: "Register Tool", path: "/tools/new", icon: "Build" },
  { label: "View Approvals", path: "/approvals", icon: "CheckCircle" },
  { label: "Settings", path: "/settings", icon: "Settings" },
];

interface Props { open: boolean; onClose: () => void; }

export default function CommandPalette({ open, onClose }: Props) {
  const navigate = useNavigate();
  const [input, setInput] = useState("");

  useEffect(() => { if (!open) setInput(""); }, [open]);

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <Autocomplete
        freeSolo
        options={actions}
        inputValue={input}
        onInputChange={(_, v) => setInput(v)}
        onChange={(_, v) => { if (v && typeof v !== "string") { navigate(v.path); onClose(); } }}
        renderInput={(params) => (
          <TextField {...params} placeholder="Search pages, tools, actions..." autoFocus
            sx={{ "& .MuiOutlinedInput-root": { fontSize: 16 } }}
            InputProps={{ ...params.InputProps, startAdornment: <SearchIcon sx={{ mr: 1, color: "text.secondary" }} /> }} />
        )}
        renderOption={(props, option) => (
          <li {...props}>
            <ListItemText primary={option.label} />
          </li>
        )}
      />
    </Dialog>
  );
}
