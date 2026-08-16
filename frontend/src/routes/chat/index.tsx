import { useState, useRef, useCallback, useEffect } from "react"
import { useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { Send, Square, MessageSquare, Plus, Trash2, Loader2, CheckCircle2, Wrench, Sparkles, Copy, Check, User, HelpCircle, AlertTriangle, Clock, Ban } from "lucide-react"
import { toast } from "sonner"
import { cn, formatTime } from "@/lib/utils"
import { useSessionsList, useMessages, useCreateSession, useArchiveSession } from "@/hooks/use-sessions"
import { useQueryClient } from "@tanstack/react-query"
import type { Session } from "@/types/session"
import { useChatRun } from "@/hooks/use-chat-run"
import { useTasks } from "@/hooks/use-tasks"
import { mapExecutionStatus } from "@/api/status"
import { summarizeRun, type RunLifecycle } from "@/api/lifecycle"
import { getRunState } from "@/api/runs"
import type { StepState } from "@/api/lifecycle"
import { Link } from "react-router-dom"

interface Msg {
  id: string
  role: "user" | "assistant"
  content: string
  ts?: string
}

function TypewriterText({ text, speed = 15 }: { text: string; speed?: number }) {
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

const PHASE_LABEL: Record<string, string> = {
  requesting: "Sending request…",
  planning: "Planning",
  validating: "Validating plan",
  executing: "Executing operations",
  approval: "Needs approval",
  clarification: "Needs clarification",
  synthesizing: "Preparing answer",
  background: "Running in background",
  complete: "Complete",
  failed: "Failed",
  cancelled: "Cancelled",
  timed_out: "Timed out",
  interrupted: "Interrupted",
  observing: "Run in progress",
}

function StepRow({ step }: { step: StepState }) {
  const pres = mapExecutionStatus(step.status === "success" ? "completed"
    : step.status === "error" ? "failed"
    : step.status === "timeout" ? "timed_out"
    : step.status === "validation_error" ? "failed"
    : step.status === "interrupted" ? "cancelled"
    : step.status)
  const running = step.status === "running" || step.status === "queued" || step.status === "retrying"
  return (
    <div className={cn("flex items-center gap-2 text-xs px-2 py-1 rounded",
      running ? "bg-muted/50" : pres.tone === "success" ? "bg-green-500/5" : pres.tone === "danger" ? "bg-red-500/5" : "bg-muted/20")}>
      {running ? <Loader2 size={12} className="animate-spin text-muted-foreground" /> :
       pres.tone === "success" ? <CheckCircle2 size={12} className="text-green-500" /> :
       pres.tone === "danger" ? <AlertTriangle size={12} className="text-destructive" /> :
       <Wrench size={12} className="text-muted-foreground" />}
      <span className="font-mono font-medium">{step.tool}</span>
      <span className={cn("text-[10px]", pres.tone === "danger" ? "text-destructive" : "text-muted-foreground")}>{pres.label}</span>
      {step.cached && <Badge variant="secondary" className="text-[9px]">cached</Badge>}
      {step.durationMs != null && <span className="text-[9px] text-muted-foreground/60 ml-auto">{Math.round(step.durationMs)}ms</span>}
      {step.error && <span className="text-[10px] text-destructive truncate max-w-[40%]" title={step.error}>{step.error}</span>}
    </div>
  )
}

function RunStatusBanner({ lifecycle }: { lifecycle: RunLifecycle }) {
  if (lifecycle.phase === "complete") return null
  const summary = summarizeRun(lifecycle)
  if (lifecycle.phase === "approval") return null
  if (lifecycle.phase === "clarification") return null
  let tone = "bg-muted/40 text-muted-foreground"
  let icon = <Loader2 size={13} className="animate-spin" />
  let text = PHASE_LABEL[lifecycle.phase] ?? lifecycle.phase

  if (lifecycle.phase === "failed") {
    tone = "bg-red-500/10 text-destructive"; icon = <AlertTriangle size={13} />
    text = lifecycle.error || "The request failed."
  } else if (lifecycle.phase === "timed_out") {
    tone = "bg-red-500/10 text-destructive"; icon = <Clock size={13} />
    text = "Timed out — the invocation wall-time budget was exceeded."
  } else if (lifecycle.phase === "interrupted") {
    tone = "bg-amber-500/10 text-amber-600 dark:text-amber-400"; icon = <Ban size={13} />
    text = "Interrupted — the invocation budget was exceeded."
  } else if (lifecycle.phase === "cancelled") {
    tone = "bg-muted/40 text-muted-foreground"; icon = <Square size={13} />
    text = "Cancelled — nothing further was executed."
  } else if (lifecycle.phase === "executing" && summary.failed > 0 && lifecycle.finalText) {
    tone = "bg-amber-500/10 text-amber-600 dark:text-amber-400"; icon = <AlertTriangle size={13} />
    text = `${summary.succeeded} of ${summary.succeeded + summary.failed} operations succeeded. ${summary.failedTools[0] ? `The ${summary.failedTools.join(", ")} operation${summary.failedTools.length > 1 ? "s" : ""} could not be completed.` : ""}`
  }

  return (
    <div className={cn("flex items-center gap-2 px-3 py-2 rounded-lg text-xs", tone)}>
      {icon}
      <span className="flex-1">{text}</span>
    </div>
  )
}

function ApprovalCard({ lifecycle, onDecision }: { lifecycle: RunLifecycle; onDecision: (text: string) => void }) {
  const approval = lifecycle.approval
  const [expiryLabel, setExpiryLabel] = useState("")
  useEffect(() => {
    if (!lifecycle.approvalExpiresAt) return
    const tick = () => {
      const remaining = lifecycle.approvalExpiresAt! - Date.now()
      if (remaining <= 0) setExpiryLabel("Expired — please re-send your request")
      else setExpiryLabel(`Expires in ${Math.ceil(remaining / 1000)}s`)
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [lifecycle.approvalExpiresAt])

  if (!approval) return null
  return (
    <div className="border border-amber-500/30 bg-amber-500/5 rounded-lg p-3 space-y-2">
      <div className="flex items-center gap-2 text-xs font-medium">
        <HelpCircle size={13} className="text-amber-500" />
        Approval required ({approval.policy || "policy"})
        {lifecycle.approvalExpiresAt && (
          <span className="text-[10px] text-muted-foreground ml-auto">{expiryLabel}</span>
        )}
      </div>
      {approval.context && <p className="text-xs text-muted-foreground">{approval.context}</p>}
      <div className="flex flex-wrap gap-1">
        {approval.tools.map((t) => <Badge key={t} variant="secondary" className="text-[10px] font-mono">{t}</Badge>)}
      </div>
      <div className="flex flex-wrap gap-1.5 pt-1">
        <Button size="sm" variant="default" onClick={() => onDecision("approve")}>Approve</Button>
        <Button size="sm" variant="outline" onClick={() => onDecision("reject")}>Reject</Button>
        <Button size="sm" variant="outline" onClick={() => onDecision("cancel")}>Cancel</Button>
        <Button size="sm" variant="ghost" onClick={() => onDecision("modify")}>Modify…</Button>
        <Button size="sm" variant="ghost" onClick={() => onDecision("What would this do?")}>Clarify</Button>
      </div>
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
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)

  const { data: pastMessages } = useMessages(currentSessionId ?? "", { page_size: 100 })
  const { lifecycle, streaming, observing, send, cancel, reconstruct } = useChatRun()
  // FE Step 3: when the run is handed to a worker, find its durable task so
  // the banner can link to /tasks/:id (TanStack Query = authoritative).
  const { data: bgTasks } = useTasks(
    { session_id: currentSessionId ?? undefined },
    lifecycle.phase === "background" && !!currentSessionId,
  )
  const bgTask = bgTasks?.tasks?.find((t) => t.task_type === "workflow_run")

  // Load from URL params
  useEffect(() => {
    const sid = searchParams.get("session")
    if (sid && sessions.find((s) => s.id === sid)) setCurrentSessionId(sid)
  }, [searchParams, sessions])

  // FE Step 2: keep the session in the URL so a refresh reconstructs the
  // SAME session (the browser is disposable; the backend owns the run).
  useEffect(() => {
    if (!currentSessionId) return
    if (searchParams.get("session") !== currentSessionId) {
      const next = new URLSearchParams(searchParams)
      next.set("session", currentSessionId)
      window.history.replaceState(null, "", `?${next.toString()}`)
    }
  }, [currentSessionId, searchParams])

  // Load past messages
  useEffect(() => {
    if (pastMessages?.items && currentSessionId) {
      const mapped: Msg[] = pastMessages.items
        .filter((m: any) => m.role === "user" || m.role === "assistant")
        .map((m: any) => ({ id: m.id, role: m.role as "user" | "assistant", content: (m.content?.text || "").toString(), ts: m.created_at }))
      setMessages(mapped)
    } else if (currentSessionId) {
      setMessages([])
    }
  }, [pastMessages, currentSessionId])

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }) }, [messages, lifecycle.phase, lifecycle.steps])

  // FE Step 2 refresh/reconnect reconstruction: the browser is disposable —
  // GET state restores phase/approval; a running server-side run is observed
  // (interval held in a ref so effect re-runs never kill the poll).
  const observeRef = useRef<{ session: string; timer?: ReturnType<typeof setInterval> } | null>(null)
  useEffect(() => {
    if (!currentSessionId) return
    if (streaming || lifecycle.phase !== "idle") return
    const tick = async () => {
      try {
        const state = await getRunState(currentSessionId)
        if (state.status === "running") {
          if (!observeRef.current || observeRef.current.session !== currentSessionId) {
            if (observeRef.current?.timer) clearInterval(observeRef.current.timer)
            observeRef.current = { session: currentSessionId, timer: setInterval(tick, 3000) }
          }
          return
        }
        // Run finished server-side — stop polling, restore the terminal phase.
        if (observeRef.current?.timer) {
          clearInterval(observeRef.current.timer)
          observeRef.current = null
        }
        await reconstruct(currentSessionId)
      } catch {
        // "No agent run found" (404) — the run may still be starting
        // server-side; keep polling until it appears or the run ends.
        if (!observeRef.current || observeRef.current.session !== currentSessionId) {
          if (observeRef.current?.timer) clearInterval(observeRef.current.timer)
          observeRef.current = { session: currentSessionId, timer: setInterval(tick, 3000) }
        }
      }
    }
    void tick()
  }, [currentSessionId, streaming, lifecycle.phase, reconstruct])

  useEffect(() => {
    return () => {
      if (observeRef.current?.timer) clearInterval(observeRef.current.timer)
      observeRef.current = null
    }
  }, [currentSessionId])

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
  }, [])

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim()) return
    let sessionId = currentSessionId
    if (!sessionId) {
      try {
        const session = await createSessionMutation.mutateAsync({ title: "New Chat" })
        sessionId = session.id
        setCurrentSessionId(session.id)
        queryClient.invalidateQueries({ queryKey: ["sessions-list"] })
      } catch { toast.error("Failed to create session"); return }
    }
    const userMsg: Msg = { id: crypto.randomUUID(), role: "user", content: text }
    setMessages((prev) => [...prev, userMsg])
    setInput("")
    await send(sessionId, text)
    queryClient.invalidateQueries({ queryKey: ["sessions-list"] })
  }, [currentSessionId, createSessionMutation, send, queryClient])

  const onApprovalDecision = useCallback((decisionText: string) => {
    if (currentSessionId) void sendMessage(decisionText)
  }, [currentSessionId, sendMessage])

  const busy = streaming || lifecycle.phase === "requesting"
  const responseStatus = lifecycle.responseStatus
  const partial = responseStatus === "PARTIAL_SUCCESS" && lifecycle.finalText

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
                      <div className="bg-muted rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm space-y-2">
                        {m.content && (
                          <div className="whitespace-pre-wrap leading-relaxed">
                            <TypewriterText text={m.content} speed={15} />
                          </div>
                        )}
                      </div>
                    )}
                    <div className={cn("flex items-center gap-2 px-1", m.role === "user" && "justify-end")}>
                      {m.ts && <span className="text-[10px] text-muted-foreground/60">{formatTime(m.ts)}</span>}
                      {m.role === "assistant" && m.content && <CopyButton text={m.content} />}
                    </div>
                  </div>
                  {m.role === "user" && (
                    <div className="shrink-0 w-7 h-7 rounded-full bg-primary flex items-center justify-center mb-1 order-2">
                      <User size={14} className="text-primary-foreground" />
                    </div>
                  )}
                </div>
              ))}

              {/* Live run panel: phase + steps + approval + banners */}
              {(streaming || observing || lifecycle.phase !== "idle") && currentSessionId && (
                <div className="max-w-[75%] space-y-2 animate-in fade-in duration-200">
                    <div className="bg-muted rounded-2xl rounded-bl-sm px-4 py-3 text-sm space-y-2">
                    {currentSessionId && (
                      <div className="flex justify-end">
                        <Link to={`/dev?session=${currentSessionId}`} className="text-[10px] text-primary hover:underline">Open Developer Console</Link>
                      </div>
                    )}
                    {lifecycle.phase === "background" ? (
                      <div className="flex items-center justify-between gap-2 bg-blue-500/10 text-blue-600 dark:text-blue-400 rounded-md px-3 py-2 text-xs">
                        <span className="flex items-center gap-2">
                          <Loader2 size={13} className="animate-spin" />
                          Running in background — you can leave this page.
                        </span>
                        <Link
                          to={bgTask ? `/tasks/${bgTask.id}` : "/tasks"}
                          className="font-medium underline underline-offset-2 hover:opacity-80"
                        >
                          {bgTask ? "View task" : "View tasks"}
                        </Link>
                      </div>
                    ) : (
                      <RunStatusBanner lifecycle={lifecycle} />
                    )}
                    {(lifecycle.phase === "planning" || lifecycle.phase === "validating" || lifecycle.phase === "executing" || lifecycle.phase === "synthesizing") && (
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Loader2 size={13} className="animate-spin" />
                        {PHASE_LABEL[lifecycle.phase]}
                        {lifecycle.phase === "executing" && Object.keys(lifecycle.steps).length > 0 && (
                          <span className="text-[10px]">({Object.keys(lifecycle.steps).length} operation{Object.keys(lifecycle.steps).length > 1 ? "s" : ""})</span>
                        )}
                      </div>
                    )}
                    {Object.keys(lifecycle.steps).length > 0 && (
                      <div className="space-y-1 pl-1 border-l-2 border-muted pl-3">
                        {Object.values(lifecycle.steps).map((step) => <StepRow key={step.taskId} step={step} />)}
                      </div>
                    )}
                    <ApprovalCard lifecycle={lifecycle} onDecision={onApprovalDecision} />
                    {partial && (
                      <div className="bg-amber-500/10 text-amber-600 dark:text-amber-400 rounded-md px-2 py-1.5 text-xs flex items-center gap-2">
                        <AlertTriangle size={12} />
                        {(() => { const s = summarizeRun(lifecycle); return `${s.succeeded} of ${s.succeeded + s.failed} operations succeeded.${s.failedTools[0] ? ` The ${s.failedTools.join(", ")} operation${s.failedTools.length > 1 ? "s" : ""} could not be completed.` : ""}` })()}
                      </div>
                    )}
                    {lifecycle.finalText && (
                      <div data-testid="run-final-text" className="whitespace-pre-wrap leading-relaxed text-sm">
                        <TypewriterText text={lifecycle.finalText} speed={10} />
                      </div>
                    )}
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            <div className="border-t p-3 flex gap-2 bg-background">
              {lifecycle.phase === "clarification" && lifecycle.clarification ? (
                <div className="flex-1 flex items-center gap-2 px-3 py-2 rounded-md bg-muted/40 text-xs text-muted-foreground">
                  <HelpCircle size={13} />
                  {lifecycle.clarification.question}
                </div>
              ) : null}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Input ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), void sendMessage(input))}
                    placeholder={lifecycle.phase === "clarification" ? "Answer to continue…" : "Ask anything..."}
                    className="flex-1" disabled={busy} />
                </TooltipTrigger>
                <TooltipContent>Press Enter to send, Shift+Enter for new line</TooltipContent>
              </Tooltip>
              {busy ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="destructive" size="icon" aria-label="Stop" onClick={() => currentSessionId && void cancel(currentSessionId)}>
                      <Square size={16} />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Stop / cancel run</TooltipContent>
                </Tooltip>
              ) : (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button size="icon" onClick={() => void sendMessage(input)} disabled={!input.trim()}><Send size={16} /></Button>
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
