import { useParams, useNavigate } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ArrowLeft, Loader2, MessageSquare, User, Sparkles } from "lucide-react"
import { useSessionDetail } from "@/hooks/use-sessions"
import { useMessages } from "@/hooks/use-chat"
import { formatDate, formatTime } from "@/lib/utils"
import { cn } from "@/lib/utils"

export default function SessionDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: session, isLoading: sessionLoading } = useSessionDetail(id!)
  const { data: messagesData, isLoading: msgsLoading } = useMessages(id!, { page_size: 200 })

  const messages = messagesData?.items ?? []

  if (sessionLoading) {
    return <div className="flex items-center justify-center py-12"><Loader2 size={24} className="animate-spin text-muted-foreground" /></div>
  }

  if (!session) {
    return (
      <div className="text-center py-12">
        <p className="text-muted-foreground">Session not found</p>
        <Button variant="outline" className="mt-4" onClick={() => navigate("/sessions")}>Back to Sessions</Button>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={() => navigate("/sessions")}><ArrowLeft size={18} /></Button>
        <div className="flex-1 min-w-0">
          <h1 className="text-xl font-bold truncate">{session.title}</h1>
          <p className="text-xs text-muted-foreground">{session.message_count} messages · {formatDate(session.created_at)}</p>
        </div>
        <Badge variant={session.status === "active" ? "success" : "secondary"}>{session.status}</Badge>
        <Button size="sm" onClick={() => navigate(`/chat?session=${session.id}`)}><MessageSquare size={14} /> Open in Chat</Button>
      </div>

      <Card>
        <CardHeader><CardTitle>Messages</CardTitle></CardHeader>
        <CardContent>
          {msgsLoading ? (
            <div className="flex justify-center py-8"><Loader2 size={20} className="animate-spin text-muted-foreground" /></div>
          ) : messages.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">No messages in this session</p>
          ) : (
            <div className="space-y-4 max-h-[60vh] overflow-auto">
              {messages.map((m: any) => {
                if (m.role !== "user" && m.role !== "assistant") return null
                const text = m.content?.text || m.content || ""
                return (
                  <div key={m.id} className={cn("flex items-start gap-2", m.role === "user" ? "justify-end" : "justify-start")}>
                    {m.role === "assistant" && (
                      <div className="shrink-0 w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center mt-1">
                        <Sparkles size={12} className="text-primary" />
                      </div>
                    )}
                    <div className={cn("max-w-[70%] rounded-2xl px-4 py-2 text-sm", m.role === "user" ? "bg-primary text-primary-foreground rounded-br-sm" : "bg-muted rounded-bl-sm")}>
                      <div className="whitespace-pre-wrap">{text}</div>
                      <div className={cn("text-[10px] mt-1", m.role === "user" ? "text-primary-foreground/60" : "text-muted-foreground/60")}>{formatTime(m.created_at)}</div>
                    </div>
                    {m.role === "user" && (
                      <div className="shrink-0 w-6 h-6 rounded-full bg-primary flex items-center justify-center mt-1">
                        <User size={12} className="text-primary-foreground" />
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
