import { Outlet } from "react-router-dom";
import { Box, Toolbar } from "@mui/material";
import Sidebar from "./Sidebar";
import TopNav from "./TopNav";
import { useSidebarStore } from "../../stores/sidebar-store";

export default function DashboardLayout() {
  const open = useSidebarStore((s) => s.open);

  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <TopNav />
      <Sidebar />
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          ml: open ? "260px" : 0,
          transition: (t) => t.transitions.create("margin"),
          p: 3,
        }}
      >
        <Toolbar />
        <Outlet />
      </Box>
    </Box>
  );
}
