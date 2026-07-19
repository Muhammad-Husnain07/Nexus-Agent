import { useNavigate, useLocation } from "react-router-dom";
import { BottomNavigation, BottomNavigationAction, Paper } from "@mui/material";
import DashboardIcon from "@mui/icons-material/Dashboard";
import ChatIcon from "@mui/icons-material/Chat";
import BuildIcon from "@mui/icons-material/Build";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import SettingsIcon from "@mui/icons-material/Settings";

export default function MobileNav() {
  const navigate = useNavigate();
  const location = useLocation();

  const tabs = [
    { label: "Dashboard", icon: <DashboardIcon />, path: "/dashboard" },
    { label: "Chat", icon: <ChatIcon />, path: "/chat" },
    { label: "Tools", icon: <BuildIcon />, path: "/tools" },
    { label: "Approvals", icon: <CheckCircleIcon />, path: "/approvals" },
    { label: "Settings", icon: <SettingsIcon />, path: "/settings" },
  ];

  const value = tabs.findIndex((t) => location.pathname.startsWith(t.path));

  return (
    <Paper sx={{ position: "fixed", bottom: 0, left: 0, right: 0, zIndex: 1200, display: { md: "none" } }} elevation={3}>
      <BottomNavigation value={value >= 0 ? value : 0} onChange={(_, i) => navigate(tabs[i].path)} showLabels>
        {tabs.map((t) => <BottomNavigationAction key={t.path} label={t.label} icon={t.icon} />)}
      </BottomNavigation>
    </Paper>
  );
}
