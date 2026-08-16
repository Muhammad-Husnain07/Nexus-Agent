import { NavLink } from "react-router-dom"
import { cn } from "@/lib/utils"
import { LayoutDashboard, MessageSquare, Wrench, FolderOpen, BrainCircuit, ListChecks, Workflow, PanelsTopLeft, Settings, X, Sparkles } from "lucide-react"

const items = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/chat", label: "Chat", icon: MessageSquare },
  { to: "/tools", label: "Tools", icon: Wrench },
  { to: "/sessions", label: "Sessions", icon: FolderOpen },
  { to: "/tasks", label: "Tasks", icon: ListChecks },
  { to: "/workflows", label: "Workflows", icon: Workflow },
  { to: "/memory", label: "Memory", icon: BrainCircuit },
  { to: "/widget", label: "Widget Studio", icon: PanelsTopLeft },
  { to: "/settings", label: "Settings", icon: Settings },
]

interface Props { open: boolean; onClose: () => void }

export default function Sidebar({ open, onClose }: Props) {
  return (
    <>
      {open && <div className="fixed inset-0 bg-black/50 z-40 md:hidden" onClick={onClose} />}
      <aside className={cn(
        "fixed md:sticky top-0 left-0 z-50 h-screen flex flex-col bg-sidebar text-sidebar-foreground border-r border-sidebar-border transition-all duration-200",
        open ? "w-64 translate-x-0" : "-translate-x-full md:translate-x-0 md:w-16"
      )}>
        {/* Logo */}
        <div className="flex items-center justify-between h-14 px-4 border-b border-sidebar-border shrink-0">
          {open && (
            <div className="flex items-center gap-2.5">
              <div className="p-1.5 rounded-lg bg-primary/20"><Sparkles size={16} className="text-primary" /></div>
              <span className="font-bold gradient-text text-lg">Nexus</span>
            </div>
          )}
          <button onClick={onClose} className="md:hidden p-1.5 hover:bg-sidebar-accent rounded-md text-sidebar-muted"><X size={16} /></button>
        </div>

        {/* Nav */}
        <nav className="flex-1 p-3 space-y-1 overflow-auto">
          {items.map((item) => {
            const Icon = item.icon
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/dashboard"}
                onClick={onClose}
                title={!open ? item.label : undefined}
                className={({ isActive }) =>
                  cn(
                    "flex items-center justify-center md:justify-start gap-3 px-3 py-2.5 rounded-lg text-sm",
                    isActive
                      ? "bg-primary/10 text-primary font-medium"
                      : "text-sidebar-muted hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
                  )
                }
              >
                <Icon size={18} className="shrink-0" />
                {open && <span>{item.label}</span>}
              </NavLink>
            )
          })}
        </nav>

        {/* Footer */}
        {open && (
          <div className="p-4 border-t border-sidebar-border">
            <p className="text-xs text-sidebar-muted/60">Nexus Agent v0.1.0</p>
            <p className="text-[10px] text-sidebar-muted/40 mt-0.5">19-node deterministic workflow compiler</p>
          </div>
        )}
      </aside>
    </>
  )
}
