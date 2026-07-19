import { useState, useRef, useCallback } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Send, Square, MessageSquare } from "lucide-react"

interface Msg { id: string; role: string; content: string }

export default function ChatPage() {
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const send = useCallback(async () => {
    if (!input.trim()) return
    const userMsg: Msg = { id: crypto.randomUUID(), role: "user", content: input }
    setMessages((prev) => [...prev, userMsg])
    setInput("")
    setLoading(true)

    const assistantId = crypto.randomUUID()
    setMessages((prev) => [...prev, { id: assistantId, role: "assistant", content: "" }])
    abortRef.current = new AbortController()

    try {
      const res = await fetch("/api/v1/sessions/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: input, stream: true }),
        signal: abortRef.current.signal,
      })
      if (!res.body) return
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() || ""
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6))
              if (data.type === "final_response" && data.payload?.text) {
                setMessages((prev) => prev.map((m) => m.id === assistantId ? { ...m, content: m.content + data.payload.text } : m))
              }
            } catch { /* skip */ }
          }
        }
      }
    } catch {
      // ignore abort errors
    } finally {
      setLoading(false)
      abortRef.current = null
    }
  }, [input])

  return (
    <div className="flex h-[calc(100vh-8rem)] gap-0">
      <div className="hidden md:flex w-64 flex-col border-r">
        <div className="p-3 border-b"><Button className="w-full" size="sm"><MessageSquare size={16} /> New Chat</Button></div>
        <div className="flex-1 overflow-auto p-2 space-y-1">
          {messages.length === 0 && <p className="text-xs text-muted-foreground text-center mt-8">No sessions</p>}
        </div>
      </div>

      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex-1 overflow-auto p-4 space-y-4">
          {messages.map((m) => (
            <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[70%] rounded-xl px-4 py-2 text-sm ${m.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted"}`}>
                {m.content || <span className="italic opacity-60">Thinking...</span>}
              </div>
            </div>
          ))}
        </div>

        <div className="border-t p-3 flex gap-2">
          <Input value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), send())}
            placeholder="Type a message..." className="flex-1"
          />
          {loading ? (
            <Button variant="destructive" size="icon" onClick={() => abortRef.current?.abort()}><Square size={16} /></Button>
          ) : (
            <Button size="icon" onClick={send} disabled={!input.trim()}><Send size={16} /></Button>
          )}
        </div>
      </div>
    </div>
  )
}
