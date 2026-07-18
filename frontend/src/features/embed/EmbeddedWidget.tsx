import { useState, useEffect, useRef, useCallback, lazy, Suspense } from "react"

interface WidgetConfig {
  apiUrl: string
  token: string
  theme?: "light" | "dark"
  primaryColor?: string
  position?: "bottom-right" | "bottom-left" | "floating-button"
  welcomeMessage?: string
  maxHeight?: number
  maxWidth?: number
  allowedDomains?: string
  customCss?: string
}

declare global {
  interface Window {
    NexusEmbed: { init: (config: WidgetConfig) => void }
    __NEXUS_WIDGET_CONFIG__?: WidgetConfig
  }
}

function FloatingButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="fixed bottom-6 right-6 z-[99999] w-14 h-14 rounded-full shadow-lg flex items-center justify-center text-white transition-transform hover:scale-110 focus:outline-none focus:ring-2 focus:ring-offset-2"
      style={{ backgroundColor: "var(--nexus-primary, #2563eb)" }}
      aria-label="Open chat"
    >
      <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="m3 21 1.9-5.7a8.5 8.5 0 1 1 3.8 3.8z" />
      </svg>
    </button>
  )
}

function ChatPanel({ config, onClose }: { config: WidgetConfig; onClose: () => void }) {
  const [messages, setMessages] = useState<Array<{ role: "user" | "agent"; content: string }>>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (config.welcomeMessage) {
      setMessages([{ role: "agent", content: config.welcomeMessage }])
    }
  }, [config.welcomeMessage])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  // PostMessage: notify parent of height changes
  useEffect(() => {
    if (panelRef.current) {
      const resizeObserver = new ResizeObserver((entries) => {
        for (const entry of entries) {
          window.parent.postMessage(
            { type: "nexus-resize", height: entry.contentRect.height, width: entry.contentRect.width },
            "*",
          )
        }
      })
      resizeObserver.observe(panelRef.current)
      return () => resizeObserver.disconnect()
    }
  }, [])

  // Listen for init messages from parent
  useEffect(() => {
    const handler = (event: MessageEvent) => {
      if (event.data?.type === "nexus-init" && event.data?.context) {
        setMessages((prev) => [
          ...prev,
          { role: "agent", content: `Context received: ${JSON.stringify(event.data.context)}` },
        ])
      }
    }
    window.addEventListener("message", handler)
    // Notify parent that widget is ready
    window.parent.postMessage({ type: "nexus-ready" }, "*")
    return () => window.removeEventListener("message", handler)
  }, [])

  const handleSend = useCallback(async () => {
    if (!input.trim() || loading) return
    const userMsg = input.trim()
    setMessages((prev) => [...prev, { role: "user", content: userMsg }])
    setInput("")
    setLoading(true)

    try {
      const resp = await fetch(`${config.apiUrl}/chat/sync`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${config.token}`,
        },
        body: JSON.stringify({ message: userMsg }),
      })
      const data = await resp.json()
      setMessages((prev) => [...prev, { role: "agent", content: data.response || data.content || JSON.stringify(data) }])
    } catch {
      setMessages((prev) => [...prev, { role: "agent", content: "Sorry, I couldn't reach the server. Please try again." }])
    } finally {
      setLoading(false)
    }
  }, [input, loading, config.apiUrl, config.token])

  const positionStyles = config.position === "bottom-left"
    ? { bottom: "80px", left: "20px" }
    : { bottom: "80px", right: "20px" }

  return (
    <div
      ref={panelRef}
      className="fixed z-[99999] flex flex-col rounded-xl shadow-2xl border overflow-hidden bg-white"
      style={{
        ...positionStyles,
        width: Math.min(config.maxWidth || 380, window.innerWidth - 40),
        height: Math.min(config.maxHeight || 600, window.innerHeight - 120),
        maxHeight: "calc(100vh - 120px)",
        "--nexus-primary": config.primaryColor || "#2563eb",
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
      } as React.CSSProperties}
      role="dialog"
      aria-label="Chat widget"
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 text-white shrink-0"
        style={{ backgroundColor: "var(--nexus-primary)" }}
      >
        <span className="font-semibold text-sm">Chat</span>
        <button
          onClick={onClose}
          className="text-white/80 hover:text-white focus:outline-none"
          aria-label="Close chat"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3 bg-gray-50">
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm ${
                msg.role === "user"
                  ? "text-white rounded-br-sm"
                  : "bg-white border rounded-bl-sm shadow-sm"
              }`}
              style={msg.role === "user" ? { backgroundColor: "var(--nexus-primary)" } : {}}
            >
              {msg.content}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-white border rounded-2xl rounded-bl-sm px-3 py-2 shadow-sm">
              <div className="flex gap-1">
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t p-3 bg-white shrink-0">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            placeholder="Type a message..."
            className="flex-1 rounded-full border px-4 py-2 text-sm focus:outline-none focus:ring-2"
            style={{ "--tw-ring-color": "var(--nexus-primary)" } as React.CSSProperties}
            disabled={loading}
            aria-label="Message input"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || loading}
            className="rounded-full p-2 text-white disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-offset-2"
            style={{ backgroundColor: "var(--nexus-primary)" }}
            aria-label="Send message"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  )
}

export default function EmbeddedWidget() {
  const [config, setConfig] = useState<WidgetConfig | null>(null)
  const [open, setOpen] = useState(false)

  // Read config from data attributes
  useEffect(() => {
    const script = document.currentScript
    if (script) {
      const cfg: WidgetConfig = {
        apiUrl: script.getAttribute("data-api-url") || import.meta.env.VITE_API_URL || "",
        token: script.getAttribute("data-token") || "",
        theme: (script.getAttribute("data-theme") as "light" | "dark") || "light",
        primaryColor: script.getAttribute("data-primary-color") || "#2563eb",
        position: (script.getAttribute("data-position") as WidgetConfig["position"]) || "bottom-right",
        welcomeMessage: script.getAttribute("data-welcome-message") || "Hello! How can I help you?",
      }
      setConfig(cfg)
    } else if (window.__NEXUS_WIDGET_CONFIG__) {
      setConfig(window.__NEXUS_WIDGET_CONFIG__)
    }
  }, [])

  // Also check for NexusEmbed global config
  useEffect(() => {
    if (window.__NEXUS_WIDGET_CONFIG__) {
      setConfig(window.__NEXUS_WIDGET_CONFIG__)
    }
  }, [])

  // Custom CSS injection
  useEffect(() => {
    if (config?.customCss) {
      const style = document.createElement("style")
      style.textContent = atob(config.customCss)
      document.head.appendChild(style)
      return () => style.remove()
    }
  }, [config?.customCss])

  if (!config) return null

  return (
    <>
      {!open && <FloatingButton onClick={() => setOpen(true)} />}
      {open && <ChatPanel config={config} onClose={() => setOpen(false)} />}
    </>
  )
}

// UMD entry point — attach to window
if (typeof window !== "undefined") {
  window.NexusEmbed = {
    init: (config: WidgetConfig) => {
      window.__NEXUS_WIDGET_CONFIG__ = config
      const root = document.createElement("div")
      root.id = "nexus-embed-root"
      document.body.appendChild(root)
      // In a real UMD build, ReactDOM.createRoot would mount here
    },
  }
}
