import { Fragment } from "react"
import { NavLink } from "react-router-dom"
import { cn } from "@/lib/utils"
import { LayoutDashboard, MessageSquare, Wrench, FolderOpen, BrainCircuit, Play, Settings, X, Sparkles } from "lucide-react"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

const items = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/chat", label: "Chat", icon: MessageSquare },
  { to: "/tools", label: "Tools", icon: Wrench },
  { to: "/sessions", label: "Sessions", icon: FolderOpen },
  { to: "/memory", label: "Memory", icon: BrainCircuit },
  { to: "/settings", label: "Settings", icon: Settings },
  { to: "/test", label: "Playground", icon: Play },
]

interface Props { open: boolean; onClose: () => void }

export default function Sidebar({ open, onClose }: Props) {
  return (
    <>
      {open && <div className="fixed inset-0 bg-black/50 z-40 md:hidden" onClick={onClose} />}
      <aside className={cn(
        "fixed md:sticky top-0 left-0 z-50 h-screen flex flex-col transition-all duration-300 bg-sidebar text-sidebar-foreground border-r border-sidebar-border",
        open ? "w-64 translate-x-0" : "-translate-x-full md:translate-x-0 md:w-16"
      )}>
        <div className="flex items-center justify-between h-14 px-4 border-b border-sidebar-border shrink-0">
          <div className={cn("flex items-center gap-2.5", open ? "flex" : "md:hidden")}>
            <div className="p-1.5 rounded-lg bg-primary/20"><Sparkles size={16} className="text-primary" /></div>
            <span className="font-bold gradient-text text-lg">Nexus</span>
          </div>
          <button onClick={onClose} className="md:hidden p-1.5 hover:bg-sidebar-accent rounded-md text-sidebar-muted"><X size={16} /></button>
        </div>

        <nav className="flex-1 p-3 space-y-1 overflow-auto">
          {items.map((item) => {
            const Icon = item.icon
            const navLink = (
              <NavLink
                to={item.to}
                end={item.to === "/dashboard"}
                onClick={onClose}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-200 group relative",
                    isActive
                      ? "bg-primary/10 text-primary font-medium"
                      : "text-sidebar-muted hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    {isActive && <span className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 rounded-full bg-primary" />}
                    <span className={cn(
                      "p-1.5 rounded-md transition-colors shrink-0 flex",
                      isActive ? "bg-primary/15" : "group-hover:bg-sidebar-accent"
                    )}>
                      <Icon size={16} />
                    </span>
                    <span className={cn("transition-opacity", open ? "opacity-100" : "md:hidden")}>{item.label}</span>
                  </>
                )}
              </NavLink>
            )

            if (!open) {
              return (
                <Tooltip key={item.to} delayDuration={0}>
                  <TooltipTrigger asChild>{navLink}</TooltipTrigger>
                  <TooltipContent side="right" className="ml-2">{item.label}</TooltipContent>
                </Tooltip>
              )
            }
            return <Fragment key={item.to}>{navLink}</Fragment>
          })}
        </nav>

        <div className={cn("p-4 border-t border-sidebar-border", open ? "block" : "md:hidden")}>
          <p className="text-xs text-sidebar-muted/60">Nexus Agent v0.1.0</p>
          <p className="text-[10px] text-sidebar-muted/40 mt-0.5">5-node LangGraph</p>
        </div>
      </aside>
    </>
  )
}
