import { useState } from "react"
import { Outlet } from "react-router-dom"
import Box from "@mui/material/Box"
import Sidebar, { DRAWER_WIDTH } from "./Sidebar"
import AppBar from "./AppBar"

export default function AppLayout() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const handleToggle = () => setMobileOpen((prev) => !prev)
  const handleClose = () => setMobileOpen(false)

  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <Sidebar open={mobileOpen} onClose={handleClose} />
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          width: { md: `calc(100% - ${DRAWER_WIDTH}px)` },
          display: "flex",
          flexDirection: "column",
        }}
      >
        <AppBar onToggleSidebar={handleToggle} />
        <Box sx={{ p: 3, flex: 1 }}>
          <Outlet />
        </Box>
      </Box>
    </Box>
  )
}
