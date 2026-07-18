import { useState } from "react"
import { Outlet } from "react-router-dom"
import Box from "@mui/material/Box"
import Toolbar from "@mui/material/Toolbar"
import Sidebar, { DRAWER_WIDTH } from "./Sidebar"
import Topbar from "./Topbar"

export default function AppLayout() {
  const [mobileOpen, setMobileOpen] = useState(false)

  const handleToggle = () => setMobileOpen((prev) => !prev)
  const handleClose = () => setMobileOpen(false)

  return (
    <Box sx={{ display: "flex" }}>
      <Topbar onToggleSidebar={handleToggle} />
      <Sidebar open={mobileOpen} onClose={handleClose} />
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          ml: { md: `${DRAWER_WIDTH}px` },
          width: { md: `calc(100% - ${DRAWER_WIDTH}px)` },
          p: 3,
        }}
      >
        <Toolbar />
        <Outlet />
      </Box>
    </Box>
  )
}
