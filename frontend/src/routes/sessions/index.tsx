import { useNavigate } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Plus, Loader2, Search } from "lucide-react"
import { useSessionsList } from "@/hooks/use-sessions"
import { formatDate } from "@/lib/utils"
import { useState } from "react"

export default function SessionsPage() {
  const navigate = useNavigate()
  const [search, setSearch] = useState("")
  const { data, isLoading } = useSessionsList({ page_size: 50 })

  const filtered = data?.items?.filter((s) =>
    s.title.toLowerCase().includes(search.toLowerCase())
  ) ?? []

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Sessions</h1>
          <p className="text-muted-foreground text-sm">Conversation history</p>
        </div>
        <Button onClick={() => navigate("/chat")}><Plus size={16} /> New Chat</Button>
      </div>

      <div className="relative">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Search sessions..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9 max-w-sm"
        />
      </div>

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex items-center justify-center py-12"><Loader2 size={24} className="animate-spin text-muted-foreground" /></div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground text-sm">No sessions found</div>
          ) : (
            <div className="divide-y">
              {filtered.map((s) => (
                <div
                  key={s.id}
                  className="flex items-center justify-between px-6 py-4 cursor-pointer hover:bg-muted/50 transition-colors"
                  onClick={() => navigate(`/sessions/${s.id}`)}
                >
                  <div className="flex-1 min-w-0">
                    <p className="font-medium truncate">{s.title}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">{s.message_count} messages · {formatDate(s.created_at)}</p>
                  </div>
                  <Badge variant={s.status === "active" ? "success" : "secondary"} className="shrink-0 ml-3">{s.status}</Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
