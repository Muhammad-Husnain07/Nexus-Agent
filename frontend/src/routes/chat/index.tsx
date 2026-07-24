import { useState, useRef, useCallback, useEffect } from "react"
import { useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { Send, Square, MessageSquare, Plus, Trash2, Loader2, CheckCircle2, Wrench, Sparkles, Copy, Check, ChevronDown, ChevronRight, User, HelpCircle } from "lucide-react"
import { toast } from "sonner"
import { cn, formatTime } from "@/lib/utils"
import { useSessionsList, useMessages, useCreateSession, useArchiveSession } from "@/hooks/use-sessions"
import { useQueryClient } from "@tanstack/react-query"
import api from "@/lib/api"
import type { Session } from "@/types/session"

interface ToolCallEvent {
  tool: string
  status: "running" | "success" | "error"
  args?: string
  result?: string
}

interface PlanStep {
  id?: string
  description?: string
  tool_name?: string | null
}

interface Msg {
  id: string
  role: "user" | "assistant"
  content: string
  plan?: PlanStep[]
  toolCalls?: ToolCallEvent[]
  reflectionScore?: number
  reflectionFeedback?: string
  ts?: string
}

async function parseSSEStream(res: Response, onEvent: (type: string, payload: any) => void, onDone?: () => void) {
  if (!res.body) { onDone?.(); return }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let currentEvent = ""

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split("\n")
      buffer = lines.pop() || ""
      for (const line of lines) {
        if (line.startsWith("event: ")) {
          currentEvent = line.slice(7).trim()
        } else if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.slice(6))
            const type = data.type || data.event || currentEvent
            const payload = data.payload || data
            onEvent(type, payload)
          } catch { /* skip malformed JSON */ }
          currentEvent = ""
        }
      }
    }
  } catch { /* stream aborted */ }
  onDone?.()
}

function TypewriterText({ text, speed = 20 }: { text: string; speed?: number }) {
  const [displayed, setDisplayed] = useState("")
  const idxRef = useRef(0)

  useEffect(() => {
    idxRef.current = 0; setDisplayed("")
    if (!text) return
    const interval = setInterval(() => {
      idxRef.current += 1
      setDisplayed(text.slice(0, idxRef.current))
      if (idxRef.current >= text.length) clearInterval(interval)
    }, speed)
    return () => clearInterval(interval)
  }, [text, speed])

  return <>{displayed}</>
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
      className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground p-1 rounded">
      {copied ? <Check size={12} /> : <Copy size={12} />}
    </button>
  )
}

function ThinkingSection({ plan, toolCalls, loading, done }: { plan?: PlanStep[]; toolCalls?: ToolCallEvent[]; loading: boolean; done: boolean }) {
  const [expanded, setExpanded] = useState(true)
  useEffect(() => { if (done) setExpanded(false) }, [done])
  if (!plan?.length && (!toolCalls || toolCalls.length === 0) && !loading) return null

  return (
    <div className="space-y-1 mb-2">
      <button onClick={() => setExpanded(!expanded)} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors w-full text-left">
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        {done ? (
          <span className="flex items-center gap-1"><CheckCircle2 size={12} className="text-green-500" /> Completed</span>
        ) : loading ? (
          <span className="flex items-center gap-1"><Loader2 size={12} className="animate-spin" /> Thinking...</span>
        ) : <span>Steps</span>}
      </button>
      {expanded && (
        <div className="space-y-1.5 pl-5 border-l-2 border-muted animate-in slide-in-from-left-1 duration-200">
          {plan?.map((step, i) => (
            <div key={i} className="flex items-center gap-2 text-xs">
              <Badge variant="outline" className={cn("h-5 w-5 p-0 flex items-center justify-center rounded-full shrink-0 text-[10px] font-mono",
                done ? "bg-green-500/10 text-green-600 border-green-200 dark:border-green-800" : "bg-muted")}>{i + 1}</Badge>
              <span className="text-muted-foreground">{step.description || step.id}</span>
              {step.tool_name && <Badge variant="secondary" className="text-[10px]">{step.tool_name}</Badge>}
            </div>
          ))}
          {toolCalls?.map((tc, i) => (
            <div key={`tc-${i}`} className={cn("flex items-center gap-2 text-xs px-2 py-1 rounded transition-colors",
              tc.status === "running" ? "bg-muted/50" : tc.status === "success" ? "bg-green-500/5" : "bg-red-500/5")}>
              {tc.status === "running" ? <Loader2 size={12} className="animate-spin text-muted-foreground" /> :
               tc.status === "success" ? <CheckCircle2 size={12} className="text-green-500" /> :
               <Wrench size={12} className="text-destructive" />}
              <span className="font-mono font-medium">{tc.tool}</span>
              {tc.status === "success" && <span className="text-green-600 dark:text-green-400">Done</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function ChatPage() {
  const [searchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const { data: sessionsData, isLoading: sessionsLoading } = useSessionsList({ page_size: 50 })
  const sessions: Session[] = [...(sessionsData?.items ?? [])].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
  const createSessionMutation = useCreateSession()
  const deleteSessionMutation = useArchiveSession()

  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)

  const { data: pastMessages } = useMessages(currentSessionId ?? "", { page_size: 100 })

  // Load from URL params
  useEffect(() => {
    const sid = searchParams.get("session")
    if (sid && sessions.find((s) => s.id === sid)) setCurrentSessionId(sid)
  }, [searchParams, sessions])

  // Load past messages
  useEffect(() => {
    if (pastMessages?.items && currentSessionId) {
      const mapped: Msg[] = pastMessages.items
        .filter((m: any) => m.role === "user" || m.role === "assistant")
        .map((m: any) => ({ id: m.id, role: m.role as "user" | "assistant", content: (m.content?.text || m.content || "").toString(), ts: m.created_at }))
      setMessages(mapped)
    } else if (currentSessionId) {
      setMessages([])
    }
  }, [pastMessages, currentSessionId])

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }) }, [messages])

  const createSession = useCallback(async () => {
    try {
      const session = await createSessionMutation.mutateAsync({ title: "New Chat" })
      setCurrentSessionId(session.id)
      setMessages([])
      queryClient.invalidateQueries({ queryKey: ["sessions-list"] })
    } catch { toast.error("Failed to create session") }
  }, [createSessionMutation, queryClient])

  const deleteSession = useCallback(async (id: string) => {
    try {
      await deleteSessionMutation.mutateAsync(id)
      if (currentSessionId === id) { setCurrentSessionId(null); setMessages([]) }
      setDeleteConfirm(null)
      queryClient.invalidateQueries({ queryKey: ["sessions-list"] })
    } catch { toast.error("Failed to delete session") }
  }, [currentSessionId, deleteSessionMutation, queryClient])

  const switchSession = useCallback((id: string) => {
    setCurrentSessionId(id)
    setMessages([])
    setLoading(false)
    abortRef.current?.abort()
  }, [])

  const send = useCallback(async () => {
    if (!input.trim()) return

    let sessionId = currentSessionId
    if (!sessionId) {
      try {
        const session = await createSessionMutation.mutateAsync({ title: "New Chat" })
        sessionId = session.id
        setCurrentSessionId(session.id)
        queryClient.invalidateQueries({ queryKey: ["sessions-list"] })
      } catch { toast.error("Failed to create session"); return }
    }

    const userMsg: Msg = { id: crypto.randomUUID(), role: "user", content: input }
    const assistantId = crypto.randomUUID()
    setMessages((prev) => [...prev, userMsg, { id: assistantId, role: "assistant", content: "", toolCalls: [] }])
    setInput("")
    setLoading(true)
    abortRef.current = new AbortController()

    try {
      const res = await fetch(`/api/v1/sessions/${sessionId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ message: input }),
        signal: abortRef.current.signal,
      })
      if (!res.ok) {
        toast.error(`Chat request failed (${res.status})`)
        setLoading(false)
        return
      }

      parseSSEStream(res,
        (type, payload) => {
          if (type === "final_response" && payload?.text) {
            setMessages((prev) => prev.map((m) => m.id === assistantId ? { ...m, content: m.content + payload.text } : m))
          } else if (type === "tool_call_completed" && payload) {
            setMessages((prev) => prev.map((m) => {
              if (m.id !== assistantId) return m
              const calls = [...(m.toolCalls || [])]
              const idx = calls.findIndex((c) => c.tool === payload.tool_name)
              if (idx >= 0) calls[idx] = { ...calls[idx], status: payload.status === "error" ? "error" : "success", result: payload.result || payload.error }
              else calls.push({ tool: payload.tool_name, status: payload.status === "error" ? "error" : "success", args: JSON.stringify(payload.args), result: payload.result || payload.error })
              return { ...m, toolCalls: calls }
            }))
          } else if (type === "tool_call_started" && payload) {
            setMessages((prev) => prev.map((m) => {
              if (m.id !== assistantId) return m
              const calls = [...(m.toolCalls || [])]
              if (!calls.find((c) => c.tool === payload.tool_name)) calls.push({ tool: payload.tool_name, status: "running" })
              return { ...m, toolCalls: calls }
            }))
          } else if (type === "plan_created" && payload?.steps) {
            setMessages((prev) => prev.map((m) => m.id === assistantId ? { ...m, plan: payload.steps } : m))
          } else if (type === "reflection_result" && payload) {
            setMessages((prev) => prev.map((m) => m.id === assistantId ? { ...m, reflectionScore: payload.score, reflectionFeedback: payload.feedback } : m))
          } else if (type === "error" && payload) {
            toast.error(payload.message || "Agent error")
          } else if (type === "done") {
            queryClient.invalidateQueries({ queryKey: ["sessions-list"] })
          }
        },
        () => { setLoading(false); abortRef.current = null; queryClient.invalidateQueries({ queryKey: ["sessions-list"] }) }
      )
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== "AbortError") toast.error("Connection lost")
      setLoading(false); abortRef.current = null
    }
  }, [input, currentSessionId, createSessionMutation, queryClient])

  return (
    <div className="flex h-[calc(100vh-8rem)] gap-0 -m-4">
      {/* Sidebar */}
      <div className="hidden md:flex w-64 flex-col border-r bg-muted/20">
        <div className="p-3 border-b">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button className="w-full" size="sm" onClick={createSession} disabled={createSessionMutation.isPending}>
                {createSessionMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />} New Chat
              </Button>
            </TooltipTrigger>
            <TooltipContent>Start a new conversation</TooltipContent>
          </Tooltip>
        </div>
        <div className="flex-1 overflow-auto p-2 space-y-1">
          {sessionsLoading && Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-9 rounded-md bg-muted/50 animate-pulse" />
          ))}
          {!sessionsLoading && sessions.length === 0 && (
            <div className="text-center py-8"><p className="text-xs text-muted-foreground">No sessions yet</p><p className="text-[10px] text-muted-foreground/60 mt-1">Start a new chat to begin</p></div>
          )}
          {sessions.map((s) => (
            <div key={s.id} onClick={() => switchSession(s.id)}
              className={cn("flex items-center justify-between px-3 py-2 rounded-md cursor-pointer text-sm transition-colors group",
                currentSessionId === s.id ? "bg-primary/10 text-primary" : "hover:bg-muted")}>
              <div className="flex items-center gap-2 truncate min-w-0">
                <MessageSquare size={14} className="shrink-0" />
                <span className="truncate">{s.title}</span>
              </div>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
                    onClick={(e) => { e.stopPropagation(); setDeleteConfirm(s.id) }}><Trash2 size={12} /></Button>
                </TooltipTrigger>
                <TooltipContent>Delete session</TooltipContent>
              </Tooltip>
            </div>
          ))}
        </div>
      </div>

      {/* Chat Area */}
      <div className="flex-1 flex flex-col min-w-0 bg-background">
        {!currentSessionId && messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-4 text-muted-foreground">
            <div className="p-4 rounded-full bg-muted"><MessageSquare size={40} className="opacity-40" /></div>
            <p className="text-sm">Start a conversation</p>
            <p className="text-xs text-muted-foreground/60">Type a message below or select a session from the sidebar</p>
            <Button onClick={createSession} disabled={createSessionMutation.isPending}><Plus size={16} /> New Chat</Button>
          </div>
        ) : (
          <>
            <div className="flex-1 overflow-auto p-4 space-y-6">
              {messages.map((m) => (
                <div key={m.id} className={cn("flex items-end gap-2 group animate-in fade-in duration-200", m.role === "user" ? "justify-end" : "justify-start")}>
                  {m.role === "assistant" && (
                    <div className="shrink-0 w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center mb-1">
                      <Sparkles size={14} className="text-primary" />
                    </div>
                  )}
                  <div className={cn("max-w-[75%] space-y-1", m.role === "user" && "order-1")}>
                    {m.role === "user" ? (
                      <div className="bg-primary text-primary-foreground rounded-2xl rounded-br-sm px-4 py-2.5 text-sm">
                        <div className="whitespace-pre-wrap">{m.content}</div>
                      </div>
                    ) : (
                      <div className="bg-muted rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm">
                        <ThinkingSection plan={m.plan} toolCalls={m.toolCalls}
                          loading={loading && m.id === messages[messages.length - 1]?.id && !m.content}
                          done={!!m.content} />
                        {m.content && (
                          <div className="whitespace-pre-wrap leading-relaxed">
                            <TypewriterText text={m.content} speed={15} />
                          </div>
                        )}
                        {!m.content && loading && (
                          <div className="flex items-center gap-2 py-2"><Loader2 size={14} className="animate-spin text-muted-foreground" /><span className="text-sm text-muted-foreground">Thinking...</span></div>
                        )}
                      </div>
                    )}
                    <div className={cn("flex items-center gap-2 px-1", m.role === "user" && "justify-end")}>
                      {m.ts && <span className="text-[10px] text-muted-foreground/60">{formatTime(m.ts)}</span>}
                      {m.role === "assistant" && m.content && <CopyButton text={m.content} />}
                      {m.role === "assistant" && m.reflectionScore !== undefined && (
                        <span className={cn("text-[10px] px-1.5 py-0.5 rounded-full",
                          m.reflectionScore >= 7 ? "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-400" : "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-400")}
                          title={m.reflectionFeedback || ""}>{m.reflectionScore}/10</span>
                      )}
                    </div>
                  </div>
                  {m.role === "user" && (
                    <div className="shrink-0 w-7 h-7 rounded-full bg-primary flex items-center justify-center mb-1 order-2">
                      <User size={14} className="text-primary-foreground" />
                    </div>
                  )}
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>

            <div className="border-t p-3 flex gap-2 bg-background">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Input ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), send())}
                    placeholder="Ask anything..." className="flex-1" disabled={loading} />
                </TooltipTrigger>
                <TooltipContent>Press Enter to send, Shift+Enter for new line</TooltipContent>
              </Tooltip>
              {loading ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="destructive" size="icon" onClick={() => { toast.info("Stream stopped"); abortRef.current?.abort() }}>
                      <Square size={16} />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Stop generating</TooltipContent>
                </Tooltip>
              ) : (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button size="icon" onClick={send} disabled={!input.trim()}><Send size={16} /></Button>
                  </TooltipTrigger>
                  <TooltipContent>Send message</TooltipContent>
                </Tooltip>
              )}
            </div>
          </>
        )}
      </div>

      {/* Delete confirmation dialog */}
      <Dialog open={!!deleteConfirm} onOpenChange={() => setDeleteConfirm(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Session</DialogTitle>
            <DialogDescription>Are you sure you want to delete this conversation? This action cannot be undone.</DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setDeleteConfirm(null)}>Cancel</Button>
            <Button variant="destructive" onClick={() => deleteSession(deleteConfirm!)} disabled={deleteSessionMutation.isPending}>
              {deleteSessionMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />} Delete
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
