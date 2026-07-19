import { useNavigate } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { MessageSquare, Wrench, CheckCircle, TrendingUp, ArrowRight } from "lucide-react"

const stats = [
  { label: "Total Sessions", value: "12", icon: MessageSquare, trend: "+3", color: "text-blue-600 dark:text-blue-400" },
  { label: "Tools Registered", value: "18", icon: Wrench, trend: "+2", color: "text-green-600 dark:text-green-400" },
  { label: "Pending Approvals", value: "3", icon: CheckCircle, trend: "", color: "text-amber-600 dark:text-amber-400" },
  { label: "Cost This Month", value: "$0.42", icon: TrendingUp, trend: "-12%", color: "text-purple-600 dark:text-purple-400" },
]

const quickActions = [
  { label: "New Chat", icon: MessageSquare, path: "/chat" },
  { label: "Register Tool", icon: Wrench, path: "/tools/new" },
  { label: "View Approvals", icon: CheckCircle, path: "/approvals" },
]

export default function DashboardPage() {
  const navigate = useNavigate()

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Welcome 👋</h1>
        <p className="text-muted-foreground">Here's what's happening with your agent.</p>
      </div>

      <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
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
              {s.trend && (
                <div className="flex items-center gap-1 mt-2 text-xs">
                  <TrendingUp size={14} className={s.trend.startsWith("+") ? "text-green-500" : "text-red-500"} />
                  <span className={s.trend.startsWith("+") ? "text-green-500" : "text-red-500"}>{s.trend} from last month</span>
                </div>
              )}
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
          <CardHeader><CardTitle>Recent Activity</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-3">
              {["Chat session created", "Tool 'get_weather' tested", "Approval pending"].map((item, i) => (
                <div key={i} className="flex items-center justify-between py-2 border-b last:border-0">
                  <span className="text-sm">{item}</span>
                  <ArrowRight size={14} className="text-muted-foreground" />
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
