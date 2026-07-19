import { NavLink } from "react-router-dom"
import { cn } from "@/lib/utils"
import { LayoutDashboard, MessageSquare, Wrench, FolderOpen, CheckCircle, BrainCircuit, Play, Code2, X } from "lucide-react"

const items = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/chat", label: "Chat", icon: MessageSquare },
  { to: "/tools", label: "Tools", icon: Wrench },
  { to: "/sessions", label: "Sessions", icon: FolderOpen },
  { to: "/approvals", label: "Approvals", icon: CheckCircle },
  { to: "/memory", label: "Memory", icon: BrainCircuit },
  { to: "/test", label: "Playground", icon: Play },
  { to: "/embed", label: "Embed", icon: Code2 },
]

interface Props { open: boolean; onClose: () => void }

export default function Sidebar({ open, onClose }: Props) {
  return (
    <>
      {open && <div className="fixed inset-0 bg-black/50 z-40 md:hidden" onClick={onClose} />}
      <aside className={cn(
        "fixed md:sticky top-0 left-0 z-50 h-screen w-64 bg-sidebar text-sidebar-foreground flex flex-col transition-transform duration-200",
        open ? "translate-x-0" : "-translate-x-full md:translate-x-0 md:w-16"
      )}>
        <div className="flex items-center justify-between p-4 border-b border-sidebar-accent">
          <span className="font-bold text-lg">Nexus</span>
          <button onClick={onClose} className="md:hidden p-1 hover:bg-sidebar-accent rounded"><X size={18} /></button>
        </div>
        <nav className="flex-1 p-2 space-y-1">
          {items.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/dashboard"}
              onClick={onClose}
              className={({ isActive }) => cn(
                "flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors",
                isActive ? "bg-sidebar-accent text-white" : "text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-foreground"
              )}
            >
              <item.icon size={18} />
              <span className={cn("transition-opacity", open ? "opacity-100" : "md:hidden")}>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="p-4 border-t border-sidebar-accent text-xs text-sidebar-foreground/50">
          Nexus Agent v0.1.0
        </div>
      </aside>
    </>
  )
}
