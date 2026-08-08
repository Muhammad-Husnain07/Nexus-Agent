import { useCallback, useEffect, useRef, useState } from "react";
import { Send, Square, Sparkles, X, MessageCircle, Check, Wrench, Loader2 } from "lucide-react";

export interface WidgetConfig {
  /** Base URL of the Nexus API (e.g. "https://api.example.com/api/v1"). */
  apiBase?: string;
  /** Widget header title. */
  title?: string;
  /** Input placeholder text. */
  placeholder?: string;
  /** Empty-state greeting message. */
  greeting?: string;
  /** Primary brand color (any CSS color). */
  primary?: string;
  /** Fixed panel height in px (default 520). */
  height?: number;
  /** Fixed panel width in px (default 380). */
  width?: number;
  /** Render as a floating launcher bubble instead of an inline panel. */
  launcher?: boolean;
  /** Launcher position: "bottom-right" | "bottom-left" | "top-right" | "top-left". */
  position?: string;
  /** Reuse an existing session id instead of creating one. */
  sessionId?: string;
  /** Persist the session id in localStorage so reloads continue the chat. */
  persistSession?: boolean;
  /** localStorage key used when persistSession is true. */
  storageKey?: string;
  /** Stacking context z-index for the widget/launcher. */
  zIndex?: number;
  /** Show streaming indicator while waiting for the final response. */
  streaming?: boolean;
  /** Callback for runtime events: final_response, approval_checkpoint, error, done. */
  onEvent?: (type: string, payload: Record<string, unknown>) => void;
  /** Render in preview mode (launcher stays inline, never position:fixed). */
  preview?: boolean;
}

interface WidgetMessage {
  role: "user" | "assistant";
  content: string;
  running?: boolean;
  tools?: string[];
  approval?: {
    message: string;
    context?: string;
    tools?: string[];
  } | null;
}

interface SSEEvent {
  type: string;
  payload?: Record<string, unknown>;
}

const DEFAULTS = {
  apiBase: "/api/v1",
  title: "Assistant",
  placeholder: "Type a message…",
  greeting: "Ask me anything about your application.",
  height: 520,
  width: 380,
  position: "bottom-right",
  storageKey: "nexus-widget-session",
  zIndex: 2147483000,
  persistSession: true,
  streaming: true,
};

function mergeConfig(config: WidgetConfig = {}): Required<Omit<WidgetConfig, "sessionId" | "onEvent" | "primary">> & Pick<WidgetConfig, "sessionId" | "onEvent" | "primary"> {
  return {
    ...DEFAULTS,
    ...config,
    apiBase: (config.apiBase || DEFAULTS.apiBase).replace(/\/+$/, ""),
  } as never;
}

function parseSSE(line: string): SSEEvent | null {
  if (!line.startsWith("data: ")) return null;
  const raw = line.slice(6).trim();
  if (!raw) return null;
  try {
    return JSON.parse(raw) as SSEEvent;
  } catch {
    return null;
  }
}

/**
 * Self-contained chat widget for embedding the Nexus runtime into any
 * third-party application. Talks to the SSE chat endpoint — no dependency
 * on the console's routing, stores, or styling beyond its own bundle.
 *
 * Conversations are persisted across reloads (localStorage) and the widget
 * handles conversational approval checkpoints inline (approve / cancel /
 * modify) so high-risk operations are decided in-chat.
 */
export default function ChatWidget(config: WidgetConfig) {
  const cfg = mergeConfig(config);
  const [messages, setMessages] = useState<WidgetMessage[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(config.sessionId ?? null);
  const [streaming, setStreaming] = useState(false);
  const [open, setOpen] = useState(!cfg.launcher);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  const emit = useCallback((type: string, payload: Record<string, unknown>) => {
    if (typeof config.onEvent === "function") {
      try {
        config.onEvent(type, payload);
      } catch {
        /* embedder callbacks must never break the widget */
      }
    }
  }, [config.onEvent]);

  // Boot: restore persisted session or create one.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        let sid = config.sessionId ?? null;
        if (!sid && cfg.persistSession) {
          try {
            sid = window.localStorage.getItem(cfg.storageKey);
          } catch {
            sid = null;
          }
        }
        if (!sid) {
          const res = await fetch(`${cfg.apiBase}/sessions`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title: cfg.title }),
          });
          const data = (await res.json()) as { id: string };
          sid = data.id;
          if (cfg.persistSession) {
            try {
              window.localStorage.setItem(cfg.storageKey, sid);
            } catch {
              /* storage unavailable — session stays in-memory */
            }
          }
        }
        if (!cancelled) setSessionId(sid);
      } catch {
        if (!cancelled) emit("error", { message: "Failed to initialize session" });
      }
    })();
    return () => {
      cancelled = true;
      abortRef.current?.abort();
    };
  }, [cfg.apiBase, cfg.storageKey, cfg.persistSession, cfg.title, config.sessionId, emit]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = useCallback(async (text: string) => {
    const msg = text.trim();
    if (!msg || !sessionId || streaming) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: msg }]);
    const assistantId = Date.now();
    setMessages((m) => [...m, { role: "assistant", content: "", running: true }]);
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;

    let acc = "";
    let tools: string[] = [];
    let approval: WidgetMessage["approval"] = null;
    try {
      const res = await fetch(`${cfg.apiBase}/sessions/${sessionId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, stream: true }),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          const evt = parseSSE(line);
          if (!evt) continue;
          const payload = evt.payload ?? {};
          emit(evt.type, payload);
          if (evt.type === "final_response" && typeof payload.text === "string") {
            acc = payload.text;
            setMessages((m) => m.map((msg_, i) =>
              i === m.length - 1 && msg_.role === "assistant"
                ? { ...msg_, content: acc, running: false }
                : msg_,
            ));
          } else if (evt.type === "tool_call_completed" && typeof payload.tool_name === "string") {
            if (!tools.includes(payload.tool_name)) tools = [...tools, payload.tool_name];
          } else if (evt.type === "tool_call_started" && typeof payload.tool_name === "string") {
            if (!tools.includes(payload.tool_name)) tools = [...tools, payload.tool_name];
          } else if (evt.type === "approval_checkpoint") {
            approval = {
              message: typeof payload.message === "string" ? payload.message : "Approval required.",
              context: typeof payload.context === "string" ? payload.context : undefined,
              tools: Array.isArray(payload.tools) ? (payload.tools as string[]) : undefined,
            };
            setMessages((m) => m.map((msg_, i) =>
              i === m.length - 1 && msg_.role === "assistant"
                ? { ...msg_, content: acc || approval!.message, running: false, approval }
                : msg_,
            ));
          } else if (evt.type === "error" && typeof payload.message === "string") {
            acc = payload.message;
            setMessages((m) => m.map((msg_, i) =>
              i === m.length - 1 && msg_.role === "assistant"
                ? { ...msg_, content: acc, running: false }
                : msg_,
            ));
          }
          if (tools.length > 0) {
            setMessages((m) => m.map((msg_, i) =>
              i === m.length - 1 && msg_.role === "assistant" && msg_.tools?.length !== tools.length
                ? { ...msg_, tools: [...tools] }
                : msg_,
            ));
          }
        }
      }
      if (!acc && !approval) {
        setMessages((m) => m.map((msg_, i) =>
          i === m.length - 1 && msg_.role === "assistant"
            ? { ...msg_, content: "I processed your request.", running: false }
            : msg_,
        ));
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setMessages((m) => m.map((msg_, i) =>
          i === m.length - 1 && msg_.role === "assistant"
            ? { ...msg_, content: "Request failed.", running: false }
            : msg_,
        ));
        emit("error", { message: "Request failed" });
      }
    } finally {
      setStreaming(false);
      void assistantId;
    }
  }, [cfg.apiBase, sessionId, streaming, emit]);

  const replyToCheckpoint = useCallback((reply: string) => {
    void send(reply);
  }, [send]);

  // Scoped CSS variables so the configured primary color actually drives the
  // widget's Tailwind `*-primary` classes (overrides the app theme locally).
  const primaryStyle: React.CSSProperties = cfg.primary
    ? ({
        "--tw-primary": cfg.primary,
        "--color-primary": cfg.primary,
        "--color-ring": cfg.primary,
      } as React.CSSProperties)
    : {};

  const panel = (
    <div
      style={{ ...primaryStyle, width: cfg.width, height: cfg.launcher ? cfg.height : undefined, zIndex: cfg.zIndex }}
      className="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-2xl border bg-background shadow-2xl"
    >
      <div className="flex items-center gap-2 border-b px-4 py-3">
        <Sparkles className="h-4 w-4 text-primary" />
        <span className="flex-1 truncate text-sm font-semibold">{cfg.title}</span>
        {cfg.launcher && (
          <button onClick={() => setOpen(false)} className="rounded p-1 text-muted-foreground hover:text-foreground" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.length === 0 && (
          <p className="pt-8 text-center text-sm text-muted-foreground">{cfg.greeting}</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className="space-y-1.5">
            <div
              className={`max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
                m.role === "user" ? "ml-auto bg-primary text-primary-foreground" : "bg-muted"
              }`}
            >
              {m.content || (m.running ? " " : "")}
              {m.running && cfg.streaming && (
                <span className="ml-1 inline-flex gap-0.5 align-middle">
                  <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
                </span>
              )}
            </div>
            {m.tools && m.tools.length > 0 && (
              <div className="flex flex-wrap gap-1 pl-1">
                {m.tools.map((t) => (
                  <span key={t} className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] text-muted-foreground">
                    <Wrench className="h-2.5 w-2.5" /> {t}
                  </span>
                ))}
              </div>
            )}
            {m.approval && (
              <div className="max-w-[85%] space-y-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
                {m.approval.context && (
                  <p className="text-xs text-amber-700 dark:text-amber-300">{m.approval.context}</p>
                )}
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => replyToCheckpoint("Yes, continue")}
                    className="inline-flex items-center gap-1 rounded-md bg-primary px-2.5 py-1 text-xs text-primary-foreground"
                  >
                    <Check className="h-3 w-3" /> Approve
                  </button>
                  <button
                    onClick={() => replyToCheckpoint("Cancel")}
                    className="rounded-md border px-2.5 py-1 text-xs"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => setInput("Modify: ")}
                    className="rounded-md border px-2.5 py-1 text-xs"
                  >
                    Modify
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>
      <div className="flex items-center gap-2 border-t p-3">
        <input
          className="flex-1 rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
          placeholder={cfg.placeholder}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send(input)}
          disabled={!sessionId || streaming}
        />
        <button
          className="rounded-md bg-primary p-2 text-primary-foreground disabled:opacity-50"
          onClick={streaming ? () => abortRef.current?.abort() : () => send(input)}
          disabled={!sessionId || (!streaming && !input.trim())}
          aria-label={streaming ? "Stop" : "Send"}
        >
          {streaming ? <Square className="h-4 w-4" /> : <Send className="h-4 w-4" />}
        </button>
      </div>
    </div>
  );

  if (!cfg.launcher) {
    return <div style={{ height: cfg.height, width: cfg.width, zIndex: cfg.zIndex }}>{panel}</div>;
  }

  const positionStyle: React.CSSProperties = config.preview
    ? { position: "relative", zIndex: cfg.zIndex, margin: "0 auto" }
    : {
        position: "fixed",
        zIndex: cfg.zIndex,
        ...(cfg.position === "bottom-left" ? { bottom: 16, left: 16 }
          : cfg.position === "top-right" ? { top: 16, right: 16 }
          : cfg.position === "top-left" ? { top: 16, left: 16 }
          : { bottom: 16, right: 16 }),
      };

  return (
    <div style={positionStyle}>
      {open && panel}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="flex h-14 w-14 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-xl"
          aria-label="Open assistant"
        >
          <MessageCircle className="h-6 w-6" />
        </button>
      )}
    </div>
  );
}
