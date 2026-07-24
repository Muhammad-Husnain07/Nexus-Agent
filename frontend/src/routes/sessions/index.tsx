import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import { useSessionsList } from "@/hooks/use-sessions"
import { MessageSquare, Search, ArrowRight, Calendar } from "lucide-react"
import { formatDate } from "@/lib/utils"

export default function SessionsPage() {
  const navigate = useNavigate()
  const [search, setSearch] = useState("")
  const { data, isLoading } = useSessionsList({ page_size: 50 })
  const sessions = (data?.items ?? [])
    .filter((s) => s.title.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Sessions</h1>
        <p className="text-sm text-muted-foreground">{data?.total ?? 0} total conversations</p>
      </div>

      <div className="relative max-w-md">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search sessions..." className="pl-8" />
      </div>

      {isLoading ? (
        <div className="space-y-2">{[...Array(5)].map((_, i) => <Skeleton key={i} className="h-16 w-full rounded-lg" />)}</div>
      ) : sessions.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          <MessageSquare size={40} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm">{search ? "No sessions match your search" : "No conversations yet"}</p>
          {!search && <p className="text-xs mt-1">Start a chat to see your sessions here</p>}
        </div>
      ) : (
        <div className="space-y-2">
          {sessions.map((s) => (
            <Card key={s.id} className="card-hover cursor-pointer" onClick={() => navigate(`/chat?session=${s.id}`)}>
              <CardContent className="p-4 flex items-center justify-between">
                <div className="flex items-center gap-3 min-w-0">
                  <div className="p-2 rounded-lg bg-primary/10"><MessageSquare size={16} className="text-primary" /></div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate">{s.title}</p>
                    <div className="flex items-center gap-3 text-xs text-muted-foreground mt-0.5">
                      <span className="flex items-center gap-1"><Calendar size={12} /> {formatDate(s.created_at)}</span>
                      <span>{s.message_count} messages</span>
                      <Badge variant={s.status === "active" ? "success" : "secondary"} className="text-[10px]">{s.status}</Badge>
                    </div>
                  </div>
                </div>
                <ArrowRight size={14} className="text-muted-foreground shrink-0" />
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
