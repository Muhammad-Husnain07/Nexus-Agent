import { Menu, Sun, Moon, Search } from "lucide-react"
import { Input } from "@/components/ui/input"
import { useLocation } from "react-router-dom"

interface Props { dark: boolean; onToggle: () => void; onMenuClick: () => void }

const pageTitles: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/chat": "Chat",
  "/tools": "Tools",
  "/sessions": "Sessions",
  "/memory": "Memory",
  "/settings": "Settings",
  "/test": "Playground",
}

export default function TopNav({ dark, onToggle, onMenuClick }: Props) {
  const location = useLocation()
  const basePath = "/" + location.pathname.split("/")[1]
  const title = pageTitles[basePath] || "Nexus Agent"

  return (
    <header className="sticky top-0 z-30 h-14 border-b bg-background/70 backdrop-blur-xl flex items-center gap-3 px-4">
      {/* Mobile menu */}
      <button onClick={onMenuClick} className="md:hidden p-2 -ml-2 hover:bg-accent rounded-lg text-muted-foreground transition-colors">
        <Menu size={18} />
      </button>

      {/* Page title */}
      <h2 className="text-sm font-semibold hidden sm:block">{title}</h2>

      {/* Search */}
      <div className="hidden sm:block relative max-w-xs flex-1">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/60" />
        <Input placeholder="Search..." className="pl-8 h-8 text-xs bg-muted/50 border-0 focus-visible:bg-background" />
      </div>

      <div className="flex-1" />

      {/* Theme toggle */}
      <button onClick={onToggle} className="p-2 hover:bg-accent rounded-lg text-muted-foreground hover:text-foreground transition-colors">
        {dark ? <Sun size={16} /> : <Moon size={16} />}
      </button>

      {/* Avatar placeholder */}
      <div className="h-7 w-7 rounded-full bg-primary/10 flex items-center justify-center">
        <span className="text-xs font-medium text-primary">N</span>
      </div>
    </header>
  )
}
