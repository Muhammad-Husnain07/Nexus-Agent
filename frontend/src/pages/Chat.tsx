import { useState, useRef, useCallback, useEffect } from "react";
import { Box, Drawer, Typography, CircularProgress, Alert } from "@mui/material";
import SessionsSidebar from "../components/Chat/SessionsSidebar";
import MessageBubble from "../components/Chat/MessageBubble";
import ToolCallCard from "../components/Chat/ToolCallCard";
import ChatInput from "../components/Chat/ChatInput";
import ContextWindowIndicator from "../components/Chat/ContextWindowIndicator";
import ApprovalRequest from "../components/Chat/ApprovalRequest";
import ExportChatModal from "../components/Chat/ExportChatModal";
import { useCreateSession, useSessions } from "../hooks/use-chat";
import api from "../lib/api";

interface ChatMessage {
  id: string; role: "user" | "assistant" | "tool" | "system"; content: string;
  tool_calls?: { tool_name: string; status: string }[];
  tool_results?: { tool_name: string; status: string; data?: unknown }[];
  created_at: string;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [rightOpen, setRightOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const { data: sessionsData } = useSessions();
  const createSession = useCreateSession();

  const handleSend = useCallback(async (text: string) => {
    let sessionId = activeSessionId;
    if (!sessionId) {
      try {
        const sess = await createSession.mutateAsync({ title: text.slice(0, 80) });
        sessionId = sess.id;
        setActiveSessionId(sessionId);
      } catch {
        setError("Failed to create session");
        return;
      }
    }
    const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", content: text, created_at: new Date().toISOString() };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);
    setStreaming(true);
    setError(null);
    abortRef.current = new AbortController();
    try {
      const res = await fetch(`/api/v1/sessions/${sessionId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, stream: true }),
        signal: abortRef.current.signal,
      });
      const reader = res.body?.getReader();
      if (!reader) throw new Error("No stream reader");
      const decoder = new TextDecoder();
      let buffer = "";
      let assistantId = crypto.randomUUID();
      setMessages((prev) => [...prev, { id: assistantId, role: "assistant", content: "", created_at: new Date().toISOString() }]);
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            const eventType = line.slice(7).trim();
            if (eventType === "tool_call_started") setRightOpen(true);
          } else if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.type === "agent_response") {
                setMessages((prev) => prev.map((m) => m.id === assistantId ? { ...m, content: m.content + (data.payload?.text || "") } : m));
              } else if (data.type === "tool_call_completed") {
                setMessages((prev) => {
                  const last = prev[prev.length - 1];
                  if (last && last.role === "assistant") {
                    return prev.map((m) => m.id === last.id ? { ...m, tool_results: [...(m.tool_results || []), { tool_name: data.payload.tool_name, status: data.payload.status, data: data.payload.data }] } : m);
                  }
                  return prev;
                });
              }
            } catch { /* ignore malformed JSON */ }
          }
        }
      }
    } catch (err: unknown) {
      if ((err as Error)?.name !== "AbortError") setError("Connection lost. Retrying...");
    } finally {
      setLoading(false);
      setStreaming(false);
      abortRef.current = null;
    }
  }, [activeSessionId, createSession]);

  const handleStop = useCallback(() => { abortRef.current?.abort(); setStreaming(false); setLoading(false); }, []);

  const allSessions = sessionsData?.items || [];

  return (
    <Box sx={{ display: "flex", height: "calc(100vh - 64px)", gap: 0 }}>
      <SessionsSidebar sessions={allSessions} activeId={activeSessionId || undefined}
        onSelect={(id) => setActiveSessionId(id)} onNew={() => { setActiveSessionId(null); setMessages([]); }} />
      <Box sx={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {error && <Alert severity="error" onClose={() => setError(null)} sx={{ mx: 2, mt: 1 }}>{error}</Alert>}
        <ContextWindowIndicator used={messages.reduce((a, m) => a + m.content.length, 0)} limit={4000} />
        <Box sx={{ flex: 1, overflowY: "auto", px: 2, py: 1 }}>
          {messages.map((msg) => (
            <Box key={msg.id}>
              {msg.role === "assistant" && msg.tool_results?.map((tr, i) => <ToolCallCard key={i} result={tr} />)}
              {msg.role !== "tool" && <MessageBubble message={msg} />}
            </Box>
          ))}
          {loading && !streaming && <Box textAlign="center" py={2}><CircularProgress size={24} /></Box>}
        </Box>
        <ChatInput onSend={handleSend} onStop={handleStop} loading={loading} />
      </Box>
      <Drawer anchor="right" open={rightOpen} onClose={() => setRightOpen(false)} sx={{ "& .MuiDrawer-paper": { width: 320 } }}>
        <Box sx={{ p: 2 }}>
          <Typography variant="subtitle2" gutterBottom>Tool Timeline</Typography>
          {messages.filter((m) => m.tool_results?.length).map((m) => m.tool_results?.map((tr, i) => <ToolCallCard key={i} result={tr} />))}
        </Box>
      </Drawer>
      <ExportChatModal open={exportOpen} onClose={() => setExportOpen(false)} />
    </Box>
  );
}
