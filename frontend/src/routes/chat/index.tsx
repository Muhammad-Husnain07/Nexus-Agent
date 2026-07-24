import { useState, useRef, useCallback, useEffect } from "react"
import { flushSync } from "react-dom"
import { useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Send, Square, MessageSquare, Plus, Trash2, Loader2, CheckCircle2, Wrench, AlertTriangle, Sparkles, Copy, Check, ChevronDown, ChevronRight, User } from "lucide-react"
import { toast } from "sonner"
import { cn, formatTime } from "@/lib/utils"
import { useSessionsList } from "@/hooks/use-sessions"
import { useMessages } from "@/hooks/use-sessions"
import { useQueryClient } from "@tanstack/react-query"

interface ToolCallEvent {
  tool: string
  status: "running" | "success" | "error"
  args?: string
  result?: string
}

interface ApprovalInfo {
  id: string
  name: string
  inputs: Record<string, unknown>
  risk_level: string
  question: string
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
  approval?: ApprovalInfo
  deciding?: boolean
  reflectionScore?: number
  reflectionFeedback?: string
  ts?: string
}

interface Session {
  id: string
  title: string
  created_at: string
  message_count: number
  status: string
}

async function parseSSEStream(res: Response, onEvent: (type: string, payload: any) => void, onDone?: () => void) {
  if (!res.body) { onDone?.(); return }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let currentEvent = ""
  let eventCount = 0

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
            // Each event gets a unique delay (0, 10, 20ms...) so they fire
            // in separate task queue entries — prevents React from batching
            // multiple flushSync calls together
            const idx = eventCount++
            setTimeout(() => queueMicrotask(() => flushSync(() => onEvent(type, payload))), idx * 10)
          } catch { /* skip */ }
          currentEvent = ""
        }
      }
    }
  } catch { /* stream error */ }
  // Schedule onDone AFTER all scheduled event callbacks have been processed
  if (eventCount > 0) {
    setTimeout(() => queueMicrotask(() => flushSync(() => onDone?.())), eventCount * 10 + 5)
  } else {
    flushSync(() => onDone?.())
  }
}

function TypewriterText({ text, speed = 20 }: { text: string; speed?: number }) {
  const [displayed, setDisplayed] = useState("")
  const idxRef = useRef(0)

  useEffect(() => {
    idxRef.current = 0
    setDisplayed("")
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
    <button
      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
      className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground p-1 rounded"
    >
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
        ) : (
          <span>Steps</span>
        )}
      </button>
      {expanded && (
        <div className="space-y-1.5 pl-5 border-l-2 border-muted animate-in slide-in-from-left-1 duration-200">
          {plan?.map((step, i) => (
            <div key={i} className="flex items-center gap-2 text-xs">
              <Badge variant="outline" className={cn(
                "h-5 w-5 p-0 flex items-center justify-center rounded-full shrink-0 text-[10px] font-mono",
                done ? "bg-green-500/10 text-green-600 border-green-200 dark:border-green-800" : "bg-muted"
              )}>{i + 1}</Badge>
              <span className="text-muted-foreground">{step.description || step.id}</span>
              {step.tool_name && <Badge variant="secondary" className="text-[10px]">{step.tool_name}</Badge>}
            </div>
          ))}
          {toolCalls?.map((tc, i) => (
            <div key={`tc-${i}`} className={cn(
              "flex items-center gap-2 text-xs px-2 py-1 rounded transition-colors",
              tc.status === "running" ? "bg-muted/50" :
              tc.status === "success" ? "bg-green-500/5" : "bg-red-500/5"
            )}>
              {tc.status === "running" ? <Loader2 size={12} className="animate-spin text-muted-foreground" /> :
               tc.status === "success" ? <CheckCircle2 size={12} className="text-green-500" /> :
               <Wrench size={12} className="text-destructive" />}
              <span className="font-mono font-medium">{tc.tool}</span>
              {tc.status === "success" && <span className="text-green-600 dark:text-green-400">Done</span>}
              {tc.result && <span className="text-muted-foreground truncate max-w-[150px]">{tc.result}</span>}
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
  const sessions: Session[] = sessionsData?.items ?? []

  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [initialMessagesLoaded, setInitialMessagesLoaded] = useState(false)
  const { data: pastMessages, isLoading: loadingPast } = useMessages(currentSessionId || "", { page_size: 100 })

  // Load past messages when switching to an existing session
  useEffect(() => {
    const sid = searchParams.get("session")
    if (sid && sessions.find((s) => s.id === sid)) {
      setCurrentSessionId(sid)
    }
  }, [searchParams, sessions])

  useEffect(() => {
    if (pastMessages?.items && messages.length === 0 && !initialMessagesLoaded) {
      const mapped: Msg[] = pastMessages.items
        .filter((m: any) => m.role === "user" || m.role === "assistant")
        .map((m: any) => ({
          id: m.id,
          role: m.role as "user" | "assistant",
          content: (m.content?.text || m.content || "").toString(),
          ts: m.created_at,
        }))
      setMessages(mapped)
      setInitialMessagesLoaded(true)
    }
  }, [pastMessages, messages.length, initialMessagesLoaded])

  // Reset loaded flag when switching sessions
  useEffect(() => {
    setInitialMessagesLoaded(false)
  }, [currentSessionId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const createSession = useCallback(async () => {
    setCreating(true)
    try {
      const res = await fetch("/api/v1/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: "New Chat" }),
      })
      if (!res.ok) { toast.error("Failed to create session"); return null }
      const session: Session = await res.json()
      setCurrentSessionId(session.id)
      setMessages([])
      queryClient.invalidateQueries({ queryKey: ["sessions"] })
      return session.id
    } catch {
      toast.error("Failed to create session")
      return null
    } finally {
      setCreating(false)
    }
  }, [queryClient])

  const deleteSession = useCallback(async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await fetch(`/api/v1/sessions/${id}`, { method: "DELETE" })
      queryClient.invalidateQueries({ queryKey: ["sessions"] })
      if (currentSessionId === id) { setCurrentSessionId(null); setMessages([]) }
    } catch { toast.error("Failed to delete session") }
  }, [currentSessionId, queryClient])

  const switchSession = useCallback((id: string) => {
    setCurrentSessionId(id)
    setMessages([])
    setInitialMessagesLoaded(false)
    setLoading(false)
    abortRef.current?.abort()
  }, [])

  const handleDecision = useCallback(async (approvalId: string, action: string, assistantId: string) => {
    setMessages((prev) => prev.map((m) =>
      m.id === assistantId ? { ...m, deciding: true, approval: undefined } : m
    ))

    try {
      const res = await fetch(`/api/v1/approvals/${approvalId}/decide?stream=true`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "text/event-stream",
          "Cache-Control": "no-cache",
        },
        body: JSON.stringify({ action }),
      })
      if (!res.ok) {
        toast.error("Failed to submit decision")
        setMessages((prev) => prev.map((m) =>
          m.id === assistantId ? { ...m, deciding: false, approval: { id: approvalId, name: "", inputs: {}, risk_level: "", question: "Failed — try again?" } } : m
        ))
        return
      }

      parseSSEStream(
        res,
        (type: string, data: any) => {
          const payload = data.payload || data
          if (type === "final_response" && payload?.text) {
            setMessages((prev) => prev.map((m) => m.id === assistantId ? { ...m, content: m.content + payload.text, deciding: false } : m))
          } else if (type === "tool_call_completed" && payload) {
            setMessages((prev) => prev.map((m) => {
              if (m.id !== assistantId) return m
              const calls = [...(m.toolCalls || [])]
              const idx = calls.findIndex((c) => c.tool === payload.tool_name)
              if (idx >= 0) {
                calls[idx] = { ...calls[idx], status: payload.status === "error" ? "error" : "success", result: payload.result || payload.error }
              } else {
                calls.push({ tool: payload.tool_name, status: payload.status === "error" ? "error" : "success", args: JSON.stringify(payload.args), result: payload.result || payload.error })
              }
              return { ...m, toolCalls: calls }
            }))
          } else if (type === "error" && payload) {
            toast.error(payload.message || "Execution error")
            setMessages((prev) => prev.map((m) => m.id === assistantId ? { ...m, deciding: false } : m))
          } else if (type === "done") {
            setMessages((prev) => prev.map((m) => m.id === assistantId ? { ...m, deciding: false } : m))
            queryClient.invalidateQueries({ queryKey: ["sessions"] })
          }
        },
        () => {
          setLoading(false)
          abortRef.current = null
          queryClient.invalidateQueries({ queryKey: ["sessions"] })
        }
      )
    } catch {
      toast.error("Failed to submit decision")
      setMessages((prev) => prev.map((m) => m.id === assistantId ? { ...m, deciding: false } : m))
      setLoading(false)
      abortRef.current = null
    }
  }, [queryClient])

  const send = useCallback(async () => {
    if (!input.trim()) return

    let sessionId = currentSessionId
    if (!sessionId) {
      sessionId = await createSession()
      if (!sessionId) return
    }

    const ts = new Date().toISOString()
    const userMsg: Msg = { id: crypto.randomUUID(), role: "user", content: input, ts }
    const assistantId = crypto.randomUUID()
    setMessages((prev) => [...prev, userMsg, { id: assistantId, role: "assistant", content: "", toolCalls: [], ts }])
    setInput("")
    setLoading(true)
    abortRef.current = new AbortController()

    try {
      const res = await fetch(`/api/v1/sessions/${sessionId}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "text/event-stream",
          "Cache-Control": "no-cache",
        },
        body: JSON.stringify({ message: input, stream: true }),
        signal: abortRef.current.signal,
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        toast.error(err?.detail || `Chat request failed (${res.status})`)
        setLoading(false)
        return
      }

      parseSSEStream(
        res,
        (type: string, data: any) => {
          const payload = data.payload || data
          if (type === "final_response" && payload?.text) {
            setMessages((prev) => prev.map((m) => m.id === assistantId ? { ...m, content: m.content + payload.text } : m))
          } else if (type === "tool_call_completed" && payload) {
            setMessages((prev) => prev.map((m) => {
              if (m.id !== assistantId) return m
              const calls = [...(m.toolCalls || [])]
              const idx = calls.findIndex((c) => c.tool === payload.tool_name)
              if (idx >= 0) {
                calls[idx] = { ...calls[idx], status: payload.status === "error" ? "error" : "success", result: payload.result || payload.error }
              } else {
                calls.push({ tool: payload.tool_name, status: payload.status === "error" ? "error" : "success", args: JSON.stringify(payload.args), result: payload.result || payload.error })
              }
              return { ...m, toolCalls: calls }
            }))
          } else if (type === "tool_call_started" && payload) {
            setMessages((prev) => prev.map((m) => {
              if (m.id !== assistantId) return m
              const calls = [...(m.toolCalls || [])]
              if (!calls.find((c) => c.tool === payload.tool_name)) {
                calls.push({ tool: payload.tool_name, status: "running", args: JSON.stringify(payload.args), result: undefined })
              }
              return { ...m, toolCalls: calls }
            }))
          } else if (type === "plan_created" && payload?.steps) {
            setMessages((prev) => prev.map((m) => {
              if (m.id !== assistantId) return m
              return { ...m, plan: payload.steps }
            }))
          } else if (type === "approval_required" && payload?.tool_call) {
            setLoading(false)
            setMessages((prev) => prev.map((m) => {
              if (m.id !== assistantId) return m
              return { ...m, approval: { id: payload.id || "", name: payload.tool_call?.name || "Unknown", inputs: payload.tool_call?.inputs || {}, risk_level: payload.risk_level || "unknown", question: payload.question || `Approve execution of '${payload.tool_call?.name}'?` } }
            }))
          } else if (type === "reflection_result" && payload) {
            setMessages((prev) => prev.map((m) => {
              if (m.id !== assistantId) return m
              return { ...m, reflectionScore: payload.score, reflectionFeedback: payload.feedback || undefined }
            }))
          } else if (type === "clarification_needed" && payload?.question) {
            setMessages((prev) => {
              if (prev.some((m) => m.id === payload.question)) return prev
              return [...prev, { id: payload.question, role: "assistant" as const, content: payload.question, ts: new Date().toISOString() }]
            })
          } else if (type === "interrupt" && payload?.question) {
            setLoading(false)
            fetch(`/api/v1/approvals/pending/${currentSessionId}`)
              .then((r) => r.json())
              .then((approvals: any[]) => {
                if (approvals.length > 0) {
                  const a = approvals[0]
                  setMessages((prev) => prev.map((m) => {
                    if (m.id !== assistantId) return m
                    return { ...m, approval: { id: a.id, name: "Review", inputs: a.interrupt_payload || {}, risk_level: "low", question: payload.question } }
                  }))
                }
              })
              .catch(() => toast.error("Failed to load pending approval"))
          } else if (type === "done") {
            queryClient.invalidateQueries({ queryKey: ["sessions"] })
          } else if (type === "error" && payload) {
            toast.error(payload.message || "Agent error")
          }
        },
        () => {
          setLoading(false)
          abortRef.current = null
          queryClient.invalidateQueries({ queryKey: ["sessions"] })
        }
      )
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== "AbortError") {
        toast.error("Connection lost")
      }
      setLoading(false)
      abortRef.current = null
    }
  }, [input, currentSessionId, createSession, queryClient])

  return (
    <div className="flex h-[calc(100vh-8rem)] gap-0 -m-4">
      <div className="hidden md:flex w-64 flex-col border-r bg-muted/20">
        <div className="p-3 border-b">
          <Button className="w-full" size="sm" onClick={createSession} disabled={creating}>
            {creating ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
            New Chat
          </Button>
        </div>
        <div className="flex-1 overflow-auto p-2 space-y-1">
          {sessionsLoading && <div className="flex justify-center py-4"><Loader2 size={16} className="animate-spin text-muted-foreground" /></div>}
          {!sessionsLoading && sessions.length === 0 && <p className="text-xs text-muted-foreground text-center mt-8">No sessions yet</p>}
          {sessions.map((s) => (
            <div key={s.id} onClick={() => switchSession(s.id)} className={cn("flex items-center justify-between px-3 py-2 rounded-md cursor-pointer text-sm transition-colors group", currentSessionId === s.id ? "bg-primary/10 text-primary" : "hover:bg-muted")}>
              <div className="flex items-center gap-2 truncate min-w-0">
                <MessageSquare size={14} className="shrink-0" />
                <span className="truncate">{s.title}</span>
              </div>
              <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" onClick={(e) => deleteSession(s.id, e)}><Trash2 size={12} /></Button>
            </div>
          ))}
        </div>
      </div>

      <div className="flex-1 flex flex-col min-w-0 bg-background">
        {!currentSessionId && messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-4 text-muted-foreground">
            <div className="p-4 rounded-full bg-muted"><MessageSquare size={40} className="opacity-40" /></div>
            <p className="text-sm">Start a conversation</p>
            <Button onClick={createSession} disabled={creating}><Plus size={16} /> New Chat</Button>
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
                        <ThinkingSection
                          plan={m.plan}
                          toolCalls={m.toolCalls}
                          loading={loading && m.id === messages[messages.length - 1]?.id && !m.content}
                          done={!!m.content}
                        />
                        {m.approval && (
                          <div className="border border-amber-200 dark:border-amber-800 rounded-lg p-3 space-y-2 bg-amber-50 dark:bg-amber-950/30 my-1">
                            <div className="flex items-center gap-2 text-amber-700 dark:text-amber-400"><AlertTriangle size={16} /><span className="font-semibold text-sm">Approval Required</span></div>
                            <p className="text-sm">{m.approval.question}</p>
                            {m.approval.name && <Badge variant={m.approval.risk_level === "high" || m.approval.risk_level === "critical" ? "destructive" : m.approval.risk_level === "medium" ? "warning" : "success"}>{m.approval.risk_level}</Badge>}
                            {Object.keys(m.approval.inputs).length > 0 && <pre className="text-xs bg-background p-2 rounded overflow-auto max-h-32">{JSON.stringify(m.approval.inputs, null, 2)}</pre>}
                            {!m.deciding ? (
                              <div className="flex gap-2 pt-1">
                                <Button size="sm" onClick={() => handleDecision(m.approval!.id, "approve", m.id)}><CheckCircle2 size={14} /> Approve</Button>
                                <Button size="sm" variant="outline" className="text-destructive border-destructive hover:bg-destructive/10" onClick={() => handleDecision(m.approval!.id, "reject", m.id)}><Square size={14} /> Reject</Button>
                              </div>
                            ) : (
                              <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 size={14} className="animate-spin" /> Processing...</div>
                            )}
                          </div>
                        )}
                        {!m.approval && m.content && (
                          <div className="whitespace-pre-wrap leading-relaxed">
                            <TypewriterText text={m.content} speed={15} />
                          </div>
                        )}
                        {!m.approval && !m.content && loading && (
                          <div className="flex items-center gap-2"><Loader2 size={14} className="animate-spin" /><span className="italic opacity-60">Thinking...</span></div>
                        )}
                      </div>
                    )}
                    <div className={cn("flex items-center gap-2 px-1", m.role === "user" && "justify-end")}>
                      {m.ts && <span className="text-[10px] text-muted-foreground/60">{formatTime(m.ts)}</span>}
                      {m.role === "assistant" && m.content && <CopyButton text={m.content} />}
                      {m.role === "assistant" && m.reflectionScore !== undefined && (
                        <span className={cn("text-[10px] px-1.5 py-0.5 rounded-full", m.reflectionScore >= 7 ? "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-400" : "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-400")} title={m.reflectionFeedback || ""}>
                          {m.reflectionScore}/10
                        </span>
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

            {!messages.some((m) => m.approval && !m.deciding) && (
              <div className="border-t p-3 flex gap-2 bg-background">
                <Input ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), send())}
                  placeholder="Ask anything..." className="flex-1" disabled={loading}
                />
                {loading ? (
                  <Button variant="destructive" size="icon" onClick={() => { toast.info("Stream stopped"); abortRef.current?.abort() }}>
                    <Square size={16} />
                  </Button>
                ) : (
                  <Button size="icon" onClick={send} disabled={!input.trim()}>
                    <Send size={16} />
                  </Button>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
