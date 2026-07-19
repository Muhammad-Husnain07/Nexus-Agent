import { Dialog, DialogTitle, DialogContent, DialogActions, IconButton } from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import type { ReactNode } from "react";

interface Props {
  open: boolean; onClose: () => void; title?: string; children: ReactNode; actions?: ReactNode;
  maxWidth?: "xs" | "sm" | "md" | "lg" | "xl"; fullWidth?: boolean;
}

export default function Modal({ open, onClose, title, children, actions, maxWidth = "sm", fullWidth = true }: Props) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth={maxWidth} fullWidth={fullWidth}>
      {title && <DialogTitle sx={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        {title}<IconButton size="small" onClick={onClose}><CloseIcon fontSize="small" /></IconButton></DialogTitle>}
      <DialogContent dividers>{children}</DialogContent>
      {actions && <DialogActions>{actions}</DialogActions>}
    </Dialog>
  );
}
