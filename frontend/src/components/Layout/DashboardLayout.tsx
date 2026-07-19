import { useLocation, Outlet } from "react-router-dom";
import { Box, Toolbar, Breadcrumbs, Link, Typography, useTheme, useMediaQuery } from "@mui/material";
import NavigateNextIcon from "@mui/icons-material/NavigateNext";
import Sidebar from "./Sidebar";
import TopNav from "./TopNav";
import MobileNav from "./MobileNav";
import { useSidebarStore } from "../../stores/sidebar-store";

const pathLabels: Record<string, string> = {
  dashboard: "Dashboard", chat: "Chat", tools: "Tools", sessions: "Sessions",
  approvals: "Approvals", memory: "Memory", "cost-analytics": "Cost Analytics",
  admin: "Admin", settings: "Settings", embed: "Embed Widget",
  tenants: "Tenants", users: "Users", "api-keys": "API Keys",
  "audit-log": "Audit Log", tokens: "Tokens", guides: "Integration Guides",
  new: "New", test: "Test Playground",
};

export default function DashboardLayout() {
  const open = useSidebarStore((s) => s.open);
  const location = useLocation();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("md"));
  const segments = location.pathname.split("/").filter(Boolean);

  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <TopNav />
      <Sidebar />
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          ml: isMobile ? 0 : open ? "260px" : 0,
          transition: (t) => t.transitions.create("margin"),
          pb: isMobile ? 7 : 0,
        }}
      >
        <Toolbar />
        <Box sx={{ px: 3, pt: 2 }}>
          <Breadcrumbs separator={<NavigateNextIcon fontSize="small" />} aria-label="breadcrumb" sx={{ mb: 1 }}>
            {segments.map((seg, i) => {
              const path = "/" + segments.slice(0, i + 1).join("/");
              const label = pathLabels[seg] || seg;
              return i === segments.length - 1 ? (
                <Typography key={path} variant="body2" color="text.primary">{label}</Typography>
              ) : (
                <Link key={path} href={path} variant="body2" color="text.secondary" underline="hover">{label}</Link>
              );
            })}
          </Breadcrumbs>
        </Box>
        <Box sx={{ px: 3, pb: 3 }}>
          <Outlet />
        </Box>
        <Box sx={{ textAlign: "center", py: 2, borderTop: 1, borderColor: "divider", mt: 4 }}>
          <Typography variant="caption" color="text.secondary">Nexus Agent v0.1.0</Typography>
        </Box>
      </Box>
      {isMobile && <MobileNav />}
    </Box>
  );
}
