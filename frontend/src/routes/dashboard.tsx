import { useState, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useSessionsList } from "@/hooks/use-sessions"
import { useToolsList } from "@/hooks/use-tools-api"
import { MessageSquare, Wrench, Plus, ArrowRight, BrainCircuit, Sparkles, Activity } from "lucide-react"
import { formatDate } from "@/lib/utils"

export default function DashboardPage() {
  const navigate = useNavigate()
  const { data: sessionsData, isLoading: sessionsLoading } = useSessionsList({ page_size: 5 })
  const { data: toolsData, isLoading: toolsLoading } = useToolsList({ page_size: 1, enabled: true })
  const [greeting, setGreeting] = useState("")

  useEffect(() => {
    const h = new Date().getHours()
    if (h < 12) setGreeting("Good morning")
    else if (h < 18) setGreeting("Good afternoon")
    else setGreeting("Good evening")
  }, [])

  const sessions = sessionsData?.items ?? []
  const totalSessions = sessionsData?.total ?? 0
  const totalTools = toolsData?.total ?? 0
  const stats = [
    { label: "Total Sessions", value: totalSessions, icon: MessageSquare, gradient: "stat-gradient-1" },
    { label: "Registered Tools", value: totalTools, icon: Wrench, gradient: "stat-gradient-2" },
    { label: "Recent Activity", value: sessions.length, icon: Activity, gradient: "stat-gradient-3" },
    { label: "Memory Items", value: "—", icon: BrainCircuit, gradient: "stat-gradient-4" },
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{greeting}</h1>
          <p className="text-sm text-muted-foreground mt-1">Here's what's happening with your agent</p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => navigate("/chat")}><Sparkles size={16} /> New Chat</Button>
          <Button variant="outline" onClick={() => navigate("/tools/new")}><Plus size={16} /> Register Tool</Button>
        </div>
      </div>

      {/* Stat Cards */}
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        {stats.map((stat, i) => (
          <div key={i} className={`${stat.gradient} rounded-xl p-5 text-white relative overflow-hidden card-hover cursor-pointer`} onClick={() => navigate(i === 0 ? "/sessions" : i === 1 ? "/tools" : i === 2 ? "/sessions" : "/memory")}>
            <div className="absolute right-2 top-2 opacity-10"><stat.icon size={48} /></div>
            <stat.icon size={20} className="opacity-80 mb-3" />
            {sessionsLoading || toolsLoading ? <Skeleton className="h-8 w-16 bg-white/20" /> : <p className="text-3xl font-bold">{stat.value}</p>}
            <p className="text-sm opacity-80 mt-1">{stat.label}</p>
          </div>
        ))}
      </div>

      {/* Quick Actions */}
      <Card>
        <CardHeader><CardTitle className="text-base">Quick Actions</CardTitle></CardHeader>
        <CardContent>
          <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
            <Button variant="outline" className="h-20 flex-col gap-1 card-hover" onClick={() => navigate("/chat")}>
              <MessageSquare size={20} /> <span className="text-xs">Start Chat</span>
            </Button>
            <Button variant="outline" className="h-20 flex-col gap-1 card-hover" onClick={() => navigate("/tools")}>
              <Wrench size={20} /> <span className="text-xs">Browse Tools</span>
            </Button>
            <Button variant="outline" className="h-20 flex-col gap-1 card-hover" onClick={() => navigate("/sessions")}>
              <Activity size={20} /> <span className="text-xs">Sessions</span>
            </Button>
            <Button variant="outline" className="h-20 flex-col gap-1 card-hover" onClick={() => navigate("/settings")}>
              <BrainCircuit size={20} /> <span className="text-xs">Settings</span>
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Recent Sessions */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base">Recent Sessions</CardTitle>
          <Button variant="ghost" size="sm" onClick={() => navigate("/sessions")}>
            View all <ArrowRight size={14} />
          </Button>
        </CardHeader>
        <CardContent>
          {sessionsLoading ? (
            <div className="space-y-3">{[...Array(3)].map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
          ) : sessions.length === 0 ? (
            <div className="text-center py-6 text-muted-foreground">
              <MessageSquare size={32} className="mx-auto mb-2 opacity-30" />
              <p className="text-sm">No conversations yet</p>
              <Button variant="outline" size="sm" className="mt-3" onClick={() => navigate("/chat")}>Start your first chat</Button>
            </div>
          ) : (
            <div className="space-y-1">
              {sessions.map((s) => (
                <div key={s.id} onClick={() => navigate(`/chat?session=${s.id}`)}
                  className="flex items-center justify-between px-3 py-2.5 rounded-lg hover:bg-muted transition-colors cursor-pointer card-hover">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="p-1.5 rounded-lg bg-primary/10"><MessageSquare size={14} className="text-primary" /></div>
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate">{s.title}</p>
                      <p className="text-xs text-muted-foreground">{s.message_count} messages · {formatDate(s.created_at)}</p>
                    </div>
                  </div>
                  <ArrowRight size={14} className="text-muted-foreground shrink-0" />
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
