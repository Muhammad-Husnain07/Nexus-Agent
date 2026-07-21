import { useNavigate } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { MessageSquare, Wrench, ArrowRight, Loader2 } from "lucide-react"
import { useSessionsList } from "@/hooks/use-sessions"
import { useToolsList } from "@/hooks/use-tools-api"
import { formatDate } from "@/lib/utils"

export default function DashboardPage() {
  const navigate = useNavigate()
  const { data: sessionsData, isLoading: sessionsLoading } = useSessionsList({ page_size: 1 })
  const { data: toolsData, isLoading: toolsLoading } = useToolsList({ page_size: 1, enabled: true })

  const sessionCount = sessionsData?.total ?? 0
  const toolCount = toolsData?.total ?? 0

  const stats = [
    { label: "Total Sessions", value: sessionsLoading ? "..." : String(sessionCount), icon: MessageSquare, color: "text-blue-600 dark:text-blue-400" },
    { label: "Tools Registered", value: toolsLoading ? "..." : String(toolCount), icon: Wrench, color: "text-green-600 dark:text-green-400" },
  ]

  const quickActions = [
    { label: "New Chat", icon: MessageSquare, path: "/chat" },
    { label: "Register Tool", icon: Wrench, path: "/tools/new" },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">Here's what's happening with your agent.</p>
      </div>

      <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
        {stats.map((s) => (
          <Card key={s.label}>
            <CardContent className="pt-6">
              <div className="flex justify-between items-start">
                <div>
                  <p className="text-sm text-muted-foreground">{s.label}</p>
                  <p className="text-2xl font-bold mt-1">{s.value}</p>
                </div>
                <div className={`p-2 rounded-lg bg-secondary ${s.color}`}><s.icon size={20} /></div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-6 grid-cols-1 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>Quick Actions</CardTitle></CardHeader>
          <CardContent>
            <div className="grid gap-3 grid-cols-1 sm:grid-cols-3">
              {quickActions.map((a) => (
                <Button key={a.label} variant="outline" className="h-24 flex-col gap-2" onClick={() => navigate(a.path)}>
                  <a.icon size={24} />
                  <span className="text-sm">{a.label}</span>
                </Button>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Recent Sessions</CardTitle></CardHeader>
          <CardContent>
            {sessionsLoading ? (
              <div className="flex items-center justify-center py-4"><Loader2 size={20} className="animate-spin text-muted-foreground" /></div>
            ) : sessionsData?.items?.length ? (
              <div className="space-y-2">
                {sessionsData.items.slice(0, 5).map((s) => (
                  <div key={s.id} className="flex items-center justify-between py-2 border-b last:border-0 cursor-pointer hover:text-primary" onClick={() => navigate(`/sessions/${s.id}`)}>
                    <span className="text-sm truncate">{s.title}</span>
                    <span className="text-xs text-muted-foreground shrink-0 ml-2">{formatDate(s.created_at)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-4">No sessions yet</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
