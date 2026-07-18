import { useLocation, useNavigate } from "react-router-dom"
import Drawer from "@mui/material/Drawer"
import Toolbar from "@mui/material/Toolbar"
import List from "@mui/material/List"
import ListItem from "@mui/material/ListItem"
import ListItemButton from "@mui/material/ListItemButton"
import ListItemIcon from "@mui/material/ListItemIcon"
import ListItemText from "@mui/material/ListItemText"
import Typography from "@mui/material/Typography"
import { MessageSquare, History, Wrench, ShieldCheck, Activity, Settings } from "lucide-react"

const DRAWER_WIDTH = 240
export { DRAWER_WIDTH }

interface NavItem {
  label: string
  path: string
  icon: React.ComponentType<{ size?: number }>
}

const NAV_ITEMS: NavItem[] = [
  { label: "Chat", path: "/", icon: MessageSquare },
  { label: "Sessions", path: "/sessions", icon: History },
  { label: "Tools", path: "/tools", icon: Wrench },
  { label: "Approvals", path: "/approvals", icon: ShieldCheck },
  { label: "Observability", path: "/observability", icon: Activity },
  { label: "Settings", path: "/settings", icon: Settings },
]

interface SidebarProps {
  open: boolean
  onClose: () => void
}

export default function Sidebar({ open, onClose }: SidebarProps) {
  const location = useLocation()
  const navigate = useNavigate()

  const isActive = (path: string) => {
    if (path === "/") return location.pathname === "/"
    return location.pathname.startsWith(path)
  }

  const handleNav = (path: string) => {
    navigate(path)
    onClose()
  }

  const content = (
    <div>
      <Toolbar>
        <Typography variant="subtitle1" sx={{ fontWeight: 700, letterSpacing: "-0.025em" }}>
          Nexus Agent
        </Typography>
      </Toolbar>
      <List>
        {NAV_ITEMS.map((item) => {
          const active = isActive(item.path)
          return (
            <ListItem key={item.path} disablePadding>
              <ListItemButton
                selected={active}
                onClick={() => handleNav(item.path)}
              >
                <ListItemIcon>
                  <item.icon size={20} />
                </ListItemIcon>
                <ListItemText primary={item.label} />
              </ListItemButton>
            </ListItem>
          )
        })}
      </List>
    </div>
  )

  return (
    <>
      <Drawer
        variant="temporary"
        open={open}
        onClose={onClose}
        ModalProps={{ keepMounted: true }}
        sx={{
          display: { xs: "block", md: "none" },
          "& .MuiDrawer-paper": { width: DRAWER_WIDTH },
        }}
      >
        {content}
      </Drawer>
      <Drawer
        variant="permanent"
        sx={{
          display: { xs: "none", md: "block" },
          "& .MuiDrawer-paper": { width: DRAWER_WIDTH, borderRight: 1, borderColor: "divider" },
        }}
      >
        {content}
      </Drawer>
    </>
  )
}
