import { useLocation, useNavigate } from "react-router-dom";
import {
  Box,
  Drawer,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Toolbar,
  Typography,
  Collapse,
  Badge,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import DashboardIcon from "@mui/icons-material/Dashboard";
import ChatIcon from "@mui/icons-material/Chat";
import BuildIcon from "@mui/icons-material/Build";
import FolderIcon from "@mui/icons-material/Folder";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import PsychologyIcon from "@mui/icons-material/Psychology";
import BarChartIcon from "@mui/icons-material/BarChart";
import ShieldIcon from "@mui/icons-material/Shield";
import CodeIcon from "@mui/icons-material/Code";
import ExpandLess from "@mui/icons-material/ExpandLess";
import ExpandMore from "@mui/icons-material/ExpandMore";
import { useState } from "react";
import { useSidebarStore } from "../../stores/sidebar-store";

const DRAWER_WIDTH = 260;

interface NavItem {
  label: string;
  icon: React.ReactNode;
  path?: string;
  badge?: number;
  children?: { label: string; path: string }[];
}

const navItems: NavItem[] = [
  { label: "Dashboard", icon: <DashboardIcon />, path: "/dashboard" },
  { label: "Chat", icon: <ChatIcon />, path: "/chat" },
  {
    label: "Tools",
    icon: <BuildIcon />,
    children: [
      { label: "All Tools", path: "/tools" },
      { label: "Create Tool", path: "/tools/new" },
    ],
  },
  { label: "Sessions", icon: <FolderIcon />, path: "/sessions" },
  { label: "Approvals", icon: <CheckCircleIcon />, path: "/approvals" },
  { label: "Memory", icon: <PsychologyIcon />, path: "/memory" },
  { label: "Cost Analytics", icon: <BarChartIcon />, path: "/cost-analytics" },
  {
    label: "Admin",
    icon: <ShieldIcon />,
    children: [
      { label: "Tenants", path: "/admin/tenants" },
      { label: "Users", path: "/admin/users" },
      { label: "API Keys", path: "/admin/api-keys" },
      { label: "Audit Log", path: "/admin/audit-log" },
    ],
  },
  { label: "Embed Widget", icon: <CodeIcon />, path: "/embed" },
];

export default function Sidebar() {
  const { open, mobileOpen, setMobileOpen, toggle } = useSidebarStore();
  const location = useLocation();
  const navigate = useNavigate();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("md"));
  const [expanded, setExpanded] = useState<string[]>([]);

  const toggleExpand = (label: string) => {
    setExpanded((prev) =>
      prev.includes(label) ? prev.filter((l) => l !== label) : [...prev, label]
    );
  };

  const isActive = (path?: string) => location.pathname === path;
  const isChildActive = (children?: { path: string }[]) =>
    children?.some((c) => location.pathname.startsWith(c.path));

  const content = (
    <Box>
      <Toolbar sx={{ px: 2 }}>
        <Typography variant="h6" fontWeight={700} noWrap>
          Nexus
        </Typography>
      </Toolbar>
      <List sx={{ px: 1 }}>
        {navItems.map((item) => {
          if (item.children) {
            const open = expanded.includes(item.label) || isChildActive(item.children);
            return (
              <Box key={item.label}>
                <ListItem disablePadding>
                  <ListItemButton
                    selected={isChildActive(item.children)}
                    onClick={() => toggleExpand(item.label)}
                    sx={{ borderRadius: 2, mb: 0.5 }}
                  >
                    <ListItemIcon sx={{ minWidth: 40 }}>{item.icon}</ListItemIcon>
                    <ListItemText primary={item.label} />
                    {open ? <ExpandLess /> : <ExpandMore />}
                  </ListItemButton>
                </ListItem>
                <Collapse in={open}>
                  <List disablePadding>
                    {item.children.map((child) => (
                      <ListItem key={child.path} disablePadding>
                        <ListItemButton
                          selected={isActive(child.path)}
                          onClick={() => {
                            navigate(child.path);
                            if (isMobile) setMobileOpen(false);
                          }}
                          sx={{ pl: 4, borderRadius: 2, mb: 0.5 }}
                        >
                          <ListItemText primary={child.label} />
                        </ListItemButton>
                      </ListItem>
                    ))}
                  </List>
                </Collapse>
              </Box>
            );
          }
          return (
            <ListItem key={item.path} disablePadding>
              <ListItemButton
                selected={isActive(item.path)}
                onClick={() => {
                  navigate(item.path!);
                  if (isMobile) setMobileOpen(false);
                }}
                sx={{ borderRadius: 2, mb: 0.5 }}
              >
                <ListItemIcon sx={{ minWidth: 40 }}>
                  {item.badge ? (
                    <Badge badgeContent={item.badge} color="error">
                      {item.icon}
                    </Badge>
                  ) : (
                    item.icon
                  )}
                </ListItemIcon>
                <ListItemText primary={item.label} />
              </ListItemButton>
            </ListItem>
          );
        })}
      </List>
    </Box>
  );

  if (isMobile) {
    return (
      <Drawer
        variant="temporary"
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        sx={{ "& .MuiDrawer-paper": { width: DRAWER_WIDTH } }}
      >
        {content}
      </Drawer>
    );
  }

  return (
    <Drawer
      variant="persistent"
      open={open}
      sx={{
        width: open ? DRAWER_WIDTH : 0,
        flexShrink: 0,
        "& .MuiDrawer-paper": {
          width: DRAWER_WIDTH,
          transition: theme.transitions.create("width"),
        },
      }}
    >
      {content}
    </Drawer>
  );
}
