/**
 * Chat transport — the ONLY place the chat SSE/JSON/WS surface is wired.
 * Components never call fetch/WebSocket for chat (FE plan immutable rule).
 */
import type { AgentEvent, ApiError, ChatRequest, ChatResponse } from "../types/api";
import { getAuthHeaders } from "./auth-store";
import { api } from "./client";
import { chatResponseSchema, parseContract } from "./contracts";

/**
 * Open a streaming chat POST. Returns the raw Response; the caller feeds
 * `res.body` into readSSEStream (src/api/stream.ts).
 */
export async function openChatStream(
  sessionId: string,
  body: ChatRequest,
  signal?: AbortSignal,
): Promise<Response> {
  return openChatStreamAt("/api/v1", sessionId, body, signal);
}

/**
 * Base-URL-aware variant used by the embeddable widget (custom apiBase).
 * Transport still lives ONLY in src/api — no component calls fetch.
 */
export async function openChatStreamAt(
  apiBase: string,
  sessionId: string,
  body: ChatRequest,
  signal?: AbortSignal,
): Promise<Response> {
  const base = apiBase.replace(/\/+$/, "");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
    "X-Request-Id": crypto.randomUUID(),
    ...getAuthHeaders(),
  };
  const res = await fetch(`${base}/sessions/${sessionId}/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    const message = await res.text().catch(() => "");
    throw {
      code: _codeForStatus(res.status),
      message: message || `Request failed (${res.status})`,
      status: res.status,
    } satisfies ApiError;
  }
  return res;
}

/** Session creation against a custom apiBase (embeddable widget). */
export async function createSessionAt(
  apiBase: string,
  title: string,
): Promise<{ id: string }> {
  const base = apiBase.replace(/\/+$/, "");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Request-Id": crypto.randomUUID(),
    ...getAuthHeaders(),
  };
  const res = await fetch(`${base}/sessions`, {
    method: "POST",
    headers,
    body: JSON.stringify({ title }),
  });
  if (!res.ok) {
    throw {
      code: _codeForStatus(res.status),
      message: `Failed to create session (${res.status})`,
      status: res.status,
    } satisfies ApiError;
  }
  return (await res.json()) as { id: string };
}

function _codeForStatus(status: number): string {
  if (status === 401) return "UNAUTHORIZED";
  if (status === 403) return "FORBIDDEN";
  if (status === 404) return "NOT_FOUND";
  if (status === 429) return "RATE_LIMITED";
  if (status >= 500) return "INTERNAL_ERROR";
  return "REQUEST_FAILED";
}

/** JSON (non-stream) chat mode — contract-validated at the boundary. */
export async function sendChatJson(
  sessionId: string,
  message: string,
): Promise<ChatResponse> {
  const raw = await api.post<unknown>(`/sessions/${sessionId}/chat`, {
    message,
    stream: false,
  });
  return parseContract("ChatResponse", chatResponseSchema, raw);
}

/**
 * Best-effort cancellation: POST the durable cancel flag (the runner polls
 * it between node events and cancels itself — the run is decoupled from
 * the observer), then the WebSocket cancel as a fallback surface.
 */
export async function cancelRun(sessionId: string, timeoutMs = 3000): Promise<boolean> {
  let acknowledged = false;
  try {
    const res = await api.post(`/sessions/${sessionId}/cancel`);
    acknowledged = res.status >= 200 && res.status < 300;
  } catch {
    acknowledged = false;
  }
  if (acknowledged) return true;
  return cancelRunOverWs(sessionId, timeoutMs);
}

async function cancelRunOverWs(sessionId: string, timeoutMs: number): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    try {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const token = getAuthHeaders()["Authorization"]?.replace("Bearer ", "");
      const url = `${proto}//${window.location.host}/api/v1/sessions/${sessionId}/ws${
        token ? `?token=${encodeURIComponent(token)}` : ""
      }`;
      const ws = new WebSocket(url);
      const timer = setTimeout(() => {
        try {
          ws.close();
        } catch {
          /* noop */
        }
        resolve(false);
      }, timeoutMs);
      ws.onopen = () => {
        try {
          ws.send(JSON.stringify({ type: "cancel" }));
        } catch {
          /* noop */
        }
      };
      ws.onmessage = (msg) => {
        try {
          const frame = JSON.parse(String(msg.data)) as { type?: string };
          if (frame.type === "cancelled") {
            clearTimeout(timer);
            ws.close();
            resolve(true);
          }
        } catch {
          /* noop */
        }
      };
      ws.onerror = () => {
        clearTimeout(timer);
        resolve(false);
      };
      ws.onclose = () => {
        clearTimeout(timer);
      };
    } catch {
      resolve(false);
    }
  });
}

/** Collect the live event stream for a session (helper for tests/debug). */
export async function collectChatEvents(
  sessionId: string,
  message: string,
  signal?: AbortSignal,
): Promise<{ events: AgentEvent[]; response: Response }> {
  const res = await openChatStream(sessionId, { message }, signal);
  const events: AgentEvent[] = [];
  const { readSSEStream } = await import("./stream");
  await readSSEStream(res.body!, { onEvent: (e) => events.push(e) });
  return { events, response: res };
}
