import { useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import Drawer from "@mui/material/Drawer"
import Toolbar from "@mui/material/Toolbar"
import List from "@mui/material/List"
import ListItem from "@mui/material/ListItem"
import ListItemButton from "@mui/material/ListItemButton"
import ListItemIcon from "@mui/material/ListItemIcon"
import ListItemText from "@mui/material/ListItemText"
import Typography from "@mui/material/Typography"
import Badge from "@mui/material/Badge"
import Divider from "@mui/material/Divider"
import Avatar from "@mui/material/Avatar"
import Menu from "@mui/material/Menu"
import MenuItem from "@mui/material/MenuItem"
import ChatIcon from "@mui/icons-material/Chat"
import HistoryIcon from "@mui/icons-material/History"
import BuildIcon from "@mui/icons-material/Build"
import VerifiedUserIcon from "@mui/icons-material/VerifiedUser"
import MemoryIcon from "@mui/icons-material/Memory"
import TimelineIcon from "@mui/icons-material/Timeline"
import SettingsIcon from "@mui/icons-material/Settings"
import PeopleIcon from "@mui/icons-material/People"
import ReceiptLongIcon from "@mui/icons-material/ReceiptLong"
import MonetizationOnIcon from "@mui/icons-material/MonetizationOn"
import Brightness4Icon from "@mui/icons-material/Brightness4"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { useAuthStore } from "@/features/auth/authStore"
import { useThemeStore } from "@/theme/themeStore"

const DRAWER_WIDTH = 240
export { DRAWER_WIDTH }

interface NavItem {
  label: string
  path: string
  icon: React.ReactNode
}

const MAIN_NAV: NavItem[] = [
  { label: "Chat", path: "/", icon: <ChatIcon /> },
  { label: "Sessions", path: "/sessions", icon: <HistoryIcon /> },
  { label: "Tools", path: "/tools", icon: <BuildIcon /> },
  { label: "Approvals", path: "/approvals", icon: <VerifiedUserIcon /> },
  { label: "Memory", path: "/memory", icon: <MemoryIcon /> },
]

const ADMIN_NAV: NavItem[] = [
  { label: "Tenants & Users", path: "/admin/tenants", icon: <PeopleIcon /> },
  { label: "Audit Log", path: "/admin/audit-log", icon: <ReceiptLongIcon /> },
]

const BOTTOM_NAV: NavItem[] = [
  { label: "Observability", path: "/observability", icon: <TimelineIcon /> },
  { label: "Cost & Usage", path: "/cost", icon: <MonetizationOnIcon /> },
  { label: "Settings", path: "/settings", icon: <SettingsIcon /> },
]

interface SidebarProps {
  open: boolean
  onClose: () => void
}

export default function Sidebar({ open, onClose }: SidebarProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const toggleMode = useThemeStore((s) => s.toggleMode)
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)
  const menuOpen = Boolean(anchorEl)
  const isAdmin = user?.role === "tenant_admin" || user?.role === "platform_admin"

  const { data: pendingApprovals } = useQuery({
    queryKey: ["approvals", "pending", "count"],
    queryFn: () => api.get("/approvals/pending").then((r) => r.data as unknown[]),
    refetchInterval: 15_000,
  })
  const pendingCount = pendingApprovals?.length || 0

  const isActive = (path: string) => {
    if (path === "/") return location.pathname === "/"
    return location.pathname.startsWith(path)
  }

  const handleNav = (path: string) => { navigate(path); onClose() }

  const handleLogout = () => { setAnchorEl(null); logout(); navigate("/login", { replace: true }) }

  const renderNavItems = (items: NavItem[], badgeMap?: Record<string, number>) =>
    items.map((item) => {
      const active = isActive(item.path)
      const badge = badgeMap?.[item.path]
      return (
        <ListItem key={item.path} disablePadding>
          <ListItemButton selected={active} onClick={() => handleNav(item.path)}>
            <ListItemIcon>
              {badge ? <Badge badgeContent={badge} color="error">{item.icon}</Badge> : item.icon}
            </ListItemIcon>
            <ListItemText primary={item.label} />
          </ListItemButton>
        </ListItem>
      )
    })

  const content = (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Toolbar>
        <Typography variant="h6" sx={{ fontWeight: 700 }}>Nexus Agent</Typography>
      </Toolbar>
      <List sx={{ flex: 1 }}>
        {renderNavItems(MAIN_NAV, { "/approvals": pendingCount })}
        {isAdmin && (
          <>
            <Divider sx={{ my: 0.5 }} />
            <ListItem disablePadding><ListItemButton disabled sx={{ cursor: "default" }}>
              <ListItemText primary="Administration" slotProps={{ primary: { variant: "caption", color: "text.secondary", sx: { px: 1 } } }} />
            </ListItemButton></ListItem>
            {renderNavItems(ADMIN_NAV)}
          </>
        )}
        <Divider sx={{ my: 0.5 }} />
        {renderNavItems(BOTTOM_NAV)}
      </List>
      <List>
        <ListItem disablePadding>
          <ListItemButton onClick={(e) => setAnchorEl(e.currentTarget)}>
            <ListItemIcon>
              <Avatar sx={{ width: 28, height: 28, fontSize: 12, bgcolor: "primary.main" }}>
                {user?.email?.charAt(0).toUpperCase() || "?"}
              </Avatar>
            </ListItemIcon>
            <ListItemText
              primary={user?.email}
              secondary={user?.tenant_id ? `Tenant ${user.tenant_id.slice(0, 8)}` : ""}
              slotProps={{ primary: { noWrap: true, variant: "body2" }, secondary: { noWrap: true, variant: "caption" } }}
            />
          </ListItemButton>
        </ListItem>
      </List>
      <Menu anchorEl={anchorEl} open={menuOpen} onClose={() => setAnchorEl(null)}>
        <MenuItem onClick={handleLogout}>Sign out</MenuItem>
        <MenuItem onClick={toggleMode}><Brightness4Icon fontSize="small" sx={{ mr: 1 }} /> Toggle theme</MenuItem>
      </Menu>
    </div>
  )

  return (
    <>
      <Drawer variant="temporary" open={open} onClose={onClose} ModalProps={{ keepMounted: true }}
        sx={{ display: { xs: "block", md: "none" }, "& .MuiDrawer-paper": { width: DRAWER_WIDTH, boxSizing: "border-box" } }}>
        {content}
      </Drawer>
      <Drawer variant="permanent"
        sx={{ display: { xs: "none", md: "block" }, width: DRAWER_WIDTH, flexShrink: 0,
          "& .MuiDrawer-paper": { width: DRAWER_WIDTH, boxSizing: "border-box" } }}>
        {content}
      </Drawer>
    </>
  )
}
