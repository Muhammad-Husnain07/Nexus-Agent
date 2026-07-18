import { useState } from "react"
import { useNavigate } from "react-router-dom"
import AppBar from "@mui/material/AppBar"
import Toolbar from "@mui/material/Toolbar"
import IconButton from "@mui/material/IconButton"
import Button from "@mui/material/Button"
import Avatar from "@mui/material/Avatar"
import Menu from "@mui/material/Menu"
import MenuItem from "@mui/material/MenuItem"
import Box from "@mui/material/Box"
import { Menu as MenuIcon, Plus, Sun, Moon } from "lucide-react"
import { toast } from "sonner"
import { useAuthStore } from "@/features/auth/authStore"
import { useThemeStore } from "@/features/theme/themeStore"
import { DRAWER_WIDTH } from "./Sidebar"

interface TopbarProps {
  onToggleSidebar: () => void
}

export default function Topbar({ onToggleSidebar }: TopbarProps) {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const themeMode = useThemeStore((s) => s.mode)
  const toggleTheme = useThemeStore((s) => s.toggleTheme)
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)
  const menuOpen = Boolean(anchorEl)

  const handleAvatarClick = (e: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(e.currentTarget)
  }

  const handleMenuClose = () => setAnchorEl(null)

  const handleLogout = () => {
    handleMenuClose()
    logout()
    navigate("/login", { replace: true })
  }

  const handleNewChat = () => toast.info("New chat coming soon")

  const avatarLetter = user?.email?.charAt(0).toUpperCase() || "?"

  return (
    <AppBar
      position="fixed"
      elevation={0}
      sx={{
        bgcolor: "background.default",
        borderBottom: 1,
        borderColor: "divider",
        ml: { md: `${DRAWER_WIDTH}px` },
        width: { md: `calc(100% - ${DRAWER_WIDTH}px)` },
      }}
    >
      <Toolbar>
        <IconButton edge="start" onClick={onToggleSidebar} sx={{ display: { md: "none" }, mr: 1 }}>
          <MenuIcon size={20} />
        </IconButton>

        <Box sx={{ flexGrow: 1 }} />

        <Button
          variant="outlined"
          size="small"
          startIcon={<Plus size={16} />}
          onClick={handleNewChat}
          sx={{ mr: 2 }}
        >
          New Chat
        </Button>

        <IconButton onClick={toggleTheme} size="small" sx={{ mr: 1 }}>
          {themeMode === "dark" ? <Sun size={18} /> : <Moon size={18} />}
        </IconButton>

        <IconButton onClick={handleAvatarClick} size="small">
          <Avatar sx={{ width: 32, height: 32, fontSize: 14, bgcolor: "primary.main" }}>
            {avatarLetter}
          </Avatar>
        </IconButton>

        <Menu
          anchorEl={anchorEl}
          open={menuOpen}
          onClose={handleMenuClose}
          transformOrigin={{ horizontal: "right", vertical: "top" }}
          anchorOrigin={{ horizontal: "right", vertical: "bottom" }}
        >
          <MenuItem disabled sx={{ opacity: 0.7, cursor: "default" }}>
            {user?.email}
          </MenuItem>
          <MenuItem onClick={handleLogout}>Sign out</MenuItem>
        </Menu>
      </Toolbar>
    </AppBar>
  )
}
