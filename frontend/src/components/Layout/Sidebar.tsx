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
      <aside
        style={{ backgroundColor: "hsl(240 5.9% 10%)", color: "hsl(240 4.8% 95.9%)" }}
        className={cn(
          "fixed md:sticky top-0 left-0 z-50 h-screen flex flex-col transition-all duration-200",
          open ? "w-64 translate-x-0" : "-translate-x-full md:translate-x-0 md:w-16"
        )}
      >
        <div className="flex items-center justify-between p-4 border-b" style={{ borderColor: "hsl(240 3.7% 15.9%)" }}>
          <span className={cn("font-bold text-lg", open ? "block" : "md:hidden")}>Nexus</span>
          <button onClick={onClose} className="md:hidden p-1 hover:opacity-70 rounded"><X size={18} /></button>
        </div>
        <nav className="flex-1 p-2 space-y-1">
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/dashboard"}
              onClick={onClose}
              title={!open ? item.label : undefined}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors",
                  isActive
                    ? "bg-white/10 text-white"
                    : "text-white/60 hover:bg-white/10 hover:text-white"
                )
              }
            >
              <item.icon size={18} className="shrink-0" />
              <span className={cn("transition-opacity", open ? "opacity-100" : "md:hidden")}>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className={cn("p-4 border-t", open ? "block" : "md:hidden")} style={{ borderColor: "hsl(240 3.7% 15.9%)" }}>
          <p className="text-xs text-white/40">Nexus Agent v0.1.0</p>
        </div>
      </aside>
    </>
  )
}
