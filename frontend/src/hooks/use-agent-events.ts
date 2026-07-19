import { useEffect, useRef, useCallback } from "react";

type Handler = (event: { type: string; data: string }) => void;

interface UseEventsOptions {
  url: string;
  onEvent: Handler;
  enabled?: boolean;
}

export function useAgentEvents({ url, onEvent, enabled = true }: UseEventsOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const retriesRef = useRef(0);

  const connect = useCallback(() => {
    if (!enabled) return;
    const ws = new WebSocket(url);
    wsRef.current = ws;
    ws.onmessage = (msg) => {
      try { const data = JSON.parse(msg.data); onEvent({ type: data.event || "message", data: data.data || msg.data }); }
      catch { onEvent({ type: "message", data: msg.data }); }
    };
    ws.onclose = () => { if (retriesRef.current < 5) { setTimeout(() => { retriesRef.current++; connect(); }, 1000 * Math.pow(2, retriesRef.current)); } };
    ws.onopen = () => { retriesRef.current = 0; };
  }, [url, onEvent, enabled]);

  useEffect(() => { connect(); return () => wsRef.current?.close(); }, [connect]);

  const send = useCallback((data: Record<string, unknown>) => { wsRef.current?.send(JSON.stringify(data)); }, []);
  return { send };
}
