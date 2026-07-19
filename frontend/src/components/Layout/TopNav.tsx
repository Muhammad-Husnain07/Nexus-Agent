import { AppBar, Toolbar, IconButton, TextField, InputAdornment, Tooltip, Box, Typography } from "@mui/material";
import MenuIcon from "@mui/icons-material/Menu";
import SearchIcon from "@mui/icons-material/Search";
import Brightness4Icon from "@mui/icons-material/Brightness4";
import Brightness7Icon from "@mui/icons-material/Brightness7";
import { useSidebarStore } from "../../stores/sidebar-store";
import { useThemeStore } from "../../stores/theme-store";

export default function TopNav() {
  const { toggle, setMobileOpen } = useSidebarStore();
  const { mode, setMode } = useThemeStore();
  const isLight = mode === "light" || (mode === "system" && window.matchMedia("(prefers-color-scheme: light)").matches);

  return (
    <AppBar position="fixed" color="inherit" elevation={0} sx={{ borderBottom: 1, borderColor: "divider" }}>
      <Toolbar>
        <IconButton edge="start" onClick={toggle} sx={{ mr: 1, display: { md: "flex" } }}><MenuIcon /></IconButton>
        <IconButton onClick={() => setMobileOpen(true)} sx={{ mr: 1, display: { md: "none" } }}><MenuIcon /></IconButton>
        <TextField size="small" placeholder="Search..." sx={{ maxWidth: 320, display: { xs: "none", sm: "block" } }}
          InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }} />
        <Box sx={{ flexGrow: 1 }} />
        <Typography variant="body2" color="text.secondary" sx={{ mr: 2 }}>Nexus Agent</Typography>
        <Tooltip title="Toggle theme">
          <IconButton onClick={() => setMode(isLight ? "dark" : "light")}>
            {isLight ? <Brightness4Icon /> : <Brightness7Icon />}
          </IconButton>
        </Tooltip>
      </Toolbar>
    </AppBar>
  );
}
