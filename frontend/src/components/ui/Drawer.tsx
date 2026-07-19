import { Drawer as MuiDrawer, Box, IconButton, Typography } from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import type { ReactNode } from "react";

interface Props { open: boolean; onClose: () => void; title?: string; children: ReactNode; anchor?: "left" | "right" | "bottom"; width?: number; }

export default function Drawer({ open, onClose, title, children, anchor = "right", width = 320 }: Props) {
  return (
    <MuiDrawer anchor={anchor} open={open} onClose={onClose} sx={{ "& .MuiDrawer-paper": { width } }}>
      {title && <Box sx={{ p: 2, display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: 1, borderColor: "divider" }}>
        <Typography variant="subtitle1">{title}</Typography><IconButton size="small" onClick={onClose}><CloseIcon fontSize="small" /></IconButton></Box>}
      <Box sx={{ p: 2 }}>{children}</Box>
    </MuiDrawer>
  );
}
