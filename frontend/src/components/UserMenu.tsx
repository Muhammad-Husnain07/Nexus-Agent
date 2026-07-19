import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  IconButton,
  Menu,
  MenuItem,
  ListItemIcon,
  ListItemText,
  Chip,
  Avatar,
  Divider,
  Typography,
  Box,
} from "@mui/material";
import AccountCircleIcon from "@mui/icons-material/AccountCircle";
import SettingsIcon from "@mui/icons-material/Settings";
import ExitToAppIcon from "@mui/icons-material/ExitToApp";
import SwapHorizIcon from "@mui/icons-material/SwapHoriz";
import { useAuth } from "../contexts/AuthContext";

const ROLE_COLORS: Record<string, string> = {
  tenant_admin: "secondary",
  developer: "primary",
  end_user: "success",
  viewer: "default",
};

export default function UserMenu() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);

  if (!user) return null;

  return (
    <>
      <IconButton onClick={(e) => setAnchorEl(e.currentTarget)}>
        <Avatar sx={{ width: 32, height: 32, bgcolor: "primary.main" }}>
          {user.email.charAt(0).toUpperCase()}
        </Avatar>
      </IconButton>
      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={() => setAnchorEl(null)}
        transformOrigin={{ horizontal: "right", vertical: "top" }}
        anchorOrigin={{ horizontal: "right", vertical: "bottom" }}
      >
        <Box sx={{ px: 2, py: 1 }}>
          <Typography variant="subtitle2">{user.email}</Typography>
          <Chip
            label={user.role.replace("_", " ")}
            size="small"
            color={ROLE_COLORS[user.role] as any || "default"}
            sx={{ mt: 0.5, textTransform: "capitalize" }}
          />
        </Box>
        <Divider />
        <MenuItem onClick={() => { setAnchorEl(null); navigate("/settings"); }}>
          <ListItemIcon><SettingsIcon fontSize="small" /></ListItemIcon>
          <ListItemText>Settings</ListItemText>
        </MenuItem>
        <MenuItem onClick={() => { setAnchorEl(null); /* TODO: switch tenant */ }}>
          <ListItemIcon><SwapHorizIcon fontSize="small" /></ListItemIcon>
          <ListItemText>Switch Tenant</ListItemText>
        </MenuItem>
        <Divider />
        <MenuItem onClick={() => { logout(); navigate("/login"); }}>
          <ListItemIcon><ExitToAppIcon fontSize="small" /></ListItemIcon>
          <ListItemText>Logout</ListItemText>
        </MenuItem>
      </Menu>
    </>
  );
}
