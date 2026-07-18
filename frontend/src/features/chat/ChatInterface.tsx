import { useState, useCallback, useRef, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Select } from "@/components/ui/select"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { ScrollArea } from "@/components/ui/scroll-area"
import { useWebSocket } from "@/hooks/use-websocket"
import { formatDuration, copyToClipboard, downloadJson } from "@/lib/utils"
import {
  Send, Bot, User, Loader2, Copy, RotateCcw, Square, Plus, Download, Filter,
  CheckCircle2, XCircle, Clock, AlertTriangle, MessageSquare, PanelRightOpen,
} from "lucide-react"
import type { ChatMessage, ToolCallInfo, SessionInfo } from "@/types/chat"

function markdownToHtml(text: string): string {
  return text
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="bg-muted p-3 rounded-md overflow-x-auto text-xs my-2"><code>$2</code></pre>')
    .replace(/`([^`]+)`/g, '<code class="bg-muted px-1 rounded text-xs">$1</code>')
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/\n/g, "<br />")
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user"
  const isAgent = message.role === "agent"
  const isTool = message.role === "tool"
  const isSystem = message.role === "system"

  if (isSystem) {
    return (
      <div className="flex justify-center my-2">
        <span className="text-xs text-muted-foreground italic bg-muted/50 px-3 py-1 rounded-full">
          {message.content}
        </span>
      </div>
    )
  }

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3`}>
      <div className={`max-w-[80%] ${isUser ? "order-1" : "order-1"}`}>
        <div className="flex items-start gap-2">
          {!isUser && (
            <div className="mt-1">
              {isAgent ? <Bot className="h-5 w-5 text-primary" /> : isTool ? <Terminal className="h-5 w-5 text-amber-500" /> : null}
            </div>
          )}
          <div>
            <div
              className={`rounded-2xl px-4 py-2 text-sm ${
                isUser
                  ? "bg-primary text-primary-foreground rounded-br-sm"
                  : isTool
                    ? "bg-amber-50 border border-amber-200 dark:bg-amber-950 dark:border-amber-800 rounded-bl-sm"
                    : "bg-muted rounded-bl-sm"
              }`}
            >
              {isTool && message.tool_call ? (
                <ToolCallContent toolCall={message.tool_call} />
              ) : (
                <span dangerouslySetInnerHTML={{ __html: markdownToHtml(message.content) }} />
              )}
            </div>
            <div className={`flex items-center gap-1 mt-0.5 ${isUser ? "justify-end" : "justify-start"}`}>
              <span className="text-[10px] text-muted-foreground">
                {new Date(message.created_at).toLocaleTimeString()}
              </span>
              <button
                className="text-[10px] text-muted-foreground hover:text-foreground opacity-0 hover:opacity-100 transition-opacity"
                onClick={() => copyToClipboard(message.content)}
              >
                <Copy className="h-3 w-3" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function ToolCallContent({ toolCall }: { toolCall: ToolCallInfo }) {
  const [expanded, setExpanded] = useState(false)

  const statusIcon = {
    pending: <Clock className="h-3 w-3 text-muted-foreground" />,
    running: <Loader2 className="h-3 w-3 text-blue-500 animate-spin" />,
    success: <CheckCircle2 className="h-3 w-3 text-green-500" />,
    error: <XCircle className="h-3 w-3 text-red-500" />,
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <span className="font-medium text-xs">{toolCall.tool_name}</span>
        {statusIcon[toolCall.status]}
        {toolCall.duration_ms !== undefined && (
          <span className="text-[10px] text-muted-foreground">{formatDuration(toolCall.duration_ms)}</span>
        )}
      </div>
      <button
        className="text-xs text-muted-foreground hover:text-foreground"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? "Hide" : "Show"} arguments
      </button>
      {expanded && (
        <pre className="text-xs font-mono bg-black/5 dark:bg-white/5 p-2 rounded mt-1 overflow-x-auto">
          {JSON.stringify(toolCall.arguments, null, 2)}
        </pre>
      )}
      {toolCall.error && (
        <div className="text-xs text-red-500 mt-1">{toolCall.error}</div>
      )}
    </div>
  )
}

function TypingIndicator() {
  return (
    <div className="flex items-start gap-2 mb-3">
      <Bot className="h-5 w-5 text-primary mt-1" />
      <div className="bg-muted rounded-2xl rounded-bl-sm px-4 py-3">
        <div className="flex gap-1">
          <span className="w-2 h-2 bg-muted-foreground rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
          <span className="w-2 h-2 bg-muted-foreground rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
          <span className="w-2 h-2 bg-muted-foreground rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
        </div>
      </div>
    </div>
  )
}

export default function ChatInterface() {
  const [messages, setMessages] = useState<ChatMessage[]>(sampleMessages)
  const [input, setInput] = useState("")
  const [isGenerating, setIsGenerating] = useState(false)
  const [sessionId, setSessionId] = useState("session-1")
  const [showTimeline, setShowTimeline] = useState(true)
  const [timelineFilter, setTimelineFilter] = useState("all")
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const ws = useWebSocket(sessionId)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const handleSend = useCallback(() => {
    if (!input.trim() || isGenerating) return
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      session_id: sessionId,
      role: "user",
      content: input.trim(),
      created_at: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, userMsg])
    setInput("")
    setIsGenerating(true)

    // Simulate agent response after delay
    setTimeout(() => {
      const agentMsg: ChatMessage = {
        id: crypto.randomUUID(),
        session_id: sessionId,
        role: "agent",
        content: `I've processed your request. Let me check the available tools to help with "${input.trim()}".`,
        created_at: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, agentMsg])
      setIsGenerating(false)
    }, 1500)
  }, [input, isGenerating, sessionId])

  const handleStop = useCallback(() => {
    setIsGenerating(false)
  }, [])

  const handleRegenerate = useCallback(() => {
    // Re-trigger last agent response
  }, [])

  const handleNewChat = useCallback(() => {
    setMessages([])
    setSessionId(crypto.randomUUID())
  }, [])

  const toolCalls = messages.filter((m) => m.role === "tool" && m.tool_call)
  const filteredToolCalls = timelineFilter === "all" ? toolCalls : toolCalls.filter((m) => m.tool_call?.status === timelineFilter)

  return (
    <div className="flex h-full flex-1 overflow-hidden">
      {/* Left: Conversation */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2 border-b bg-background/95 backdrop-blur shrink-0">
          <div className="flex items-center gap-2">
            <Select
              value={sessionId}
              onChange={(e) => setSessionId(e.target.value)}
              options={[
                { value: "session-1", label: "Current Session" },
                { value: "session-2", label: "Previous Session" },
              ]}
            />
            <Button variant="ghost" size="icon" onClick={handleNewChat} title="New Chat">
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" onClick={() => setShowTimeline(!showTimeline)} title="Toggle Timeline">
              <PanelRightOpen className="h-4 w-4" />
            </Button>
            <Button variant="ghost" size="icon" onClick={() => downloadJson(messages, "conversation.json")} title="Export">
              <Download className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Messages */}
        <ScrollArea className="flex-1 px-4 py-4">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
              <MessageSquare className="h-12 w-12 mb-4 opacity-50" />
              <p className="text-lg font-medium">Start a conversation</p>
              <p className="text-sm">Ask the agent to perform tasks using registered tools</p>
            </div>
          )}
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
          {isGenerating && <TypingIndicator />}
          <div ref={messagesEndRef} />
        </ScrollArea>

        {/* Input */}
        <div className="border-t p-4 bg-background shrink-0">
          <div className="flex gap-2 max-w-4xl mx-auto">
            {isGenerating && (
              <Button variant="ghost" size="icon" onClick={handleStop} title="Stop">
                <Square className="h-4 w-4 text-destructive" />
              </Button>
            )}
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
              placeholder="Ask the agent to do something..."
              disabled={isGenerating}
              className="flex-1"
            />
            <Button onClick={handleSend} disabled={!input.trim() || isGenerating}>
              <Send className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="icon" onClick={handleRegenerate} disabled={messages.length === 0} title="Regenerate">
              <RotateCcw className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>

      {/* Right: Tool timeline */}
      {showTimeline && (
        <div className="w-80 border-l bg-muted/20 flex flex-col shrink-0">
          <div className="p-3 border-b">
            <div className="flex items-center justify-between mb-2">
              <h3 className="font-semibold text-sm">Tool Timeline</h3>
              <Filter className="h-3 w-3 text-muted-foreground" />
            </div>
            <Select
              value={timelineFilter}
              onChange={(e) => setTimelineFilter(e.target.value)}
              options={[
                { value: "all", label: "All" },
                { value: "success", label: "Success" },
                { value: "error", label: "Error" },
                { value: "running", label: "Running" },
              ]}
            />
          </div>
          <ScrollArea className="flex-1 p-3">
            {filteredToolCalls.length === 0 ? (
              <p className="text-xs text-muted-foreground text-center py-8">No tool calls yet</p>
            ) : (
              <div className="space-y-2">
                {filteredToolCalls.map((msg) => (
                  <Card key={msg.id} className="text-xs">
                    <CardContent className="p-3">
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-medium">{msg.tool_call?.tool_name}</span>
                        <Badge variant={
                          msg.tool_call?.status === "success" ? "success" as any :
                          msg.tool_call?.status === "error" ? "destructive" as any :
                          "default"
                        } className="text-[10px]">
                          {msg.tool_call?.status}
                        </Badge>
                      </div>
                      {msg.tool_call?.duration_ms !== undefined && (
                        <div className="text-muted-foreground">{formatDuration(msg.tool_call.duration_ms)}</div>
                      )}
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </ScrollArea>
        </div>
      )}
    </div>
  )
}

import { Terminal } from "lucide-react"

const sampleMessages: ChatMessage[] = [
  {
    id: "1", session_id: "session-1", role: "user",
    content: "Can you search for products with the keyword 'wireless headphones'?",
    created_at: new Date(Date.now() - 60000).toISOString(),
  },
  {
    id: "2", session_id: "session-1", role: "agent",
    content: "I'll search for wireless headphones using the product search tool.",
    created_at: new Date(Date.now() - 55000).toISOString(),
  },
  {
    id: "3", session_id: "session-1", role: "tool",
    content: "",
    tool_call: {
      tool_name: "search-products",
      arguments: { query: "wireless headphones", limit: 10 },
      status: "success",
      result: { items: [{ name: "Sony WH-1000XM5", price: 349.99 }, { name: "AirPods Pro", price: 249.99 }] },
      duration_ms: 423,
    },
    created_at: new Date(Date.now() - 54000).toISOString(),
  },
  {
    id: "4", session_id: "session-1", role: "agent",
    content: "Here are the results for **wireless headphones**:\n\n1. **Sony WH-1000XM5** — $349.99\n2. **AirPods Pro** — $249.99\n\nWould you like more details on any of these?",
    created_at: new Date(Date.now() - 53000).toISOString(),
  },
]
