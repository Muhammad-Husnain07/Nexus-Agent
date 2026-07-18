import { useLocation, useNavigate } from "react-router-dom"
import MuiAppBar from "@mui/material/AppBar"
import Toolbar from "@mui/material/Toolbar"
import IconButton from "@mui/material/IconButton"
import Button from "@mui/material/Button"
import Typography from "@mui/material/Typography"
import Tooltip from "@mui/material/Tooltip"
import MenuIcon from "@mui/icons-material/Menu"
import AddIcon from "@mui/icons-material/Add"
import Brightness4Icon from "@mui/icons-material/Brightness4"
import Brightness7Icon from "@mui/icons-material/Brightness7"
import Breadcrumbs from "@mui/material/Breadcrumbs"
import Link from "@mui/material/Link"
import { useThemeStore } from "@/theme/themeStore"
import { DRAWER_WIDTH } from "./Sidebar"

interface AppBarProps {
  onToggleSidebar: () => void
}

const PATH_LABELS: Record<string, string> = {
  "": "Chat",
  chat: "Chat",
  sessions: "Sessions",
  tools: "Tools",
  approvals: "Approvals",
  observability: "Observability",
  settings: "Settings",
}

export default function AppBar({ onToggleSidebar }: AppBarProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const mode = useThemeStore((s) => s.mode)
  const toggleMode = useThemeStore((s) => s.toggleMode)

  const segments = location.pathname.split("/").filter(Boolean)

  return (
    <MuiAppBar
      position="sticky"
      elevation={0}
      sx={{
        bgcolor: "background.default",
        borderBottom: 1,
        borderColor: "divider",
        width: { md: `calc(100% - ${DRAWER_WIDTH}px)` },
        ml: { md: `${DRAWER_WIDTH}px` },
      }}
    >
      <Toolbar>
        <IconButton edge="start" onClick={onToggleSidebar} sx={{ display: { md: "none" }, mr: 1 }} aria-label="open sidebar">
          <MenuIcon />
        </IconButton>

        <Breadcrumbs aria-label="navigation">
          {segments.length === 0 ? (
            <Typography variant="body2" color="text.primary" sx={{ fontWeight: 500 }}>
              Chat
            </Typography>
          ) : (
            segments.map((seg, i) => {
              const path = "/" + segments.slice(0, i + 1).join("/")
              const label = PATH_LABELS[seg] || seg
              return i === segments.length - 1 ? (
                <Typography key={path} variant="body2" color="text.primary" sx={{ fontWeight: 500 }}>
                  {label}
                </Typography>
              ) : (
                <Link key={path} href={path} underline="hover" color="text.secondary" variant="body2" onClick={(e) => { e.preventDefault(); navigate(path) }}>
                  {label}
                </Link>
              )
            })
          )}
        </Breadcrumbs>

        <div style={{ flex: 1 }} />

        <Button variant="contained" size="small" startIcon={<AddIcon />} onClick={() => navigate("/")} sx={{ mr: 1 }}>
          New Chat
        </Button>

        <Tooltip title={mode === "dark" ? "Switch to light mode" : "Switch to dark mode"}>
          <IconButton onClick={toggleMode} aria-label="toggle theme">
            {mode === "dark" ? <Brightness7Icon /> : <Brightness4Icon />}
          </IconButton>
        </Tooltip>
      </Toolbar>
    </MuiAppBar>
  )
}
