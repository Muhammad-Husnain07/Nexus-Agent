import { useParams, useNavigate } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useSessionDetail, useMessages } from "@/hooks/use-sessions"
import { ArrowLeft, MessageSquare, Calendar, MessagesSquare, ExternalLink, User, Sparkles } from "lucide-react"
import { formatDate } from "@/lib/utils"
import { cn } from "@/lib/utils"

export default function SessionDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: session, isLoading } = useSessionDetail(id!)
  const { data: messagesData, isLoading: msgsLoading } = useMessages(id!, { page_size: 200 })

  if (isLoading) return <div className="space-y-4">{[...Array(3)].map((_, i) => <Skeleton key={i} className="h-20 w-full rounded-xl" />)}</div>
  if (!session) return <div className="text-center py-16 text-muted-foreground"><MessageSquare size={48} className="mx-auto mb-4 opacity-30" /><p className="text-lg">Session not found</p><Button variant="outline" className="mt-4" onClick={() => navigate("/sessions")}>Back to Sessions</Button></div>

  const messages = messagesData?.items?.filter((m: any) => m.role === "user" || m.role === "assistant") || []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start gap-4">
        <Button variant="ghost" size="icon" className="mt-1" onClick={() => navigate("/sessions")}><ArrowLeft size={18} /></Button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-primary/10"><MessageSquare size={18} className="text-primary" /></div>
            <div>
              <h1 className="text-xl font-bold truncate">{session.title}</h1>
              <div className="flex items-center gap-3 text-xs text-muted-foreground mt-0.5">
                <span className="flex items-center gap-1"><Calendar size={12} /> {formatDate(session.created_at)}</span>
                <span className="flex items-center gap-1"><MessagesSquare size={12} /> {session.message_count} messages</span>
                <Badge variant={session.status === "active" ? "success" : "secondary"} className="text-[10px]">{session.status}</Badge>
              </div>
            </div>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={() => navigate(`/chat?session=${session.id}`)}><ExternalLink size={14} /> Open in Chat</Button>
      </div>

      {/* Messages */}
      <Card>
        <CardHeader><CardTitle className="text-base">Messages ({messages.length})</CardTitle></CardHeader>
        <CardContent>
          {msgsLoading ? (
            <div className="space-y-3">{[...Array(3)].map((_, i) => <Skeleton key={i} className="h-16 w-full rounded-lg" />)}</div>
          ) : messages.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">No messages in this session</p>
          ) : (
            <div className="space-y-2">
              {messages.map((m: any) => (
                <div key={m.id} className={cn("flex items-start gap-3 p-3 rounded-lg", m.role === "user" ? "bg-primary/5" : "bg-muted/30")}>
                  <div className={cn("p-1.5 rounded-lg shrink-0", m.role === "user" ? "bg-primary/10" : "bg-muted")}>
                    {m.role === "user" ? <User size={14} className="text-primary" /> : <Sparkles size={14} className="text-muted-foreground" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium mb-0.5">{m.role === "user" ? "You" : "Assistant"}</p>
                    <p className="text-sm whitespace-pre-wrap">{(m.content?.text || m.content || "").toString()}</p>
                    <p className="text-[10px] text-muted-foreground/60 mt-1">{formatDate(m.created_at)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
