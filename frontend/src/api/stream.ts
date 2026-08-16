/**
 * THE single SSE parser + event dispatcher (FE plan immutable rule).
 *
 * Backend framing (nexus-agent/src/nexus/api/chat.py):
 *   event: <type>
 *   data: <json envelope {type, ts, payload}>
 *   : keep-alive   (comment heartbeat every 10s — ignored)
 *   event: done / data: {}
 * Headers: Cache-Control: no-cache, X-Accel-Buffering: no
 */
import type { AgentEvent } from "../types/api";
import { USER_VISIBLE_EVENTS } from "../types/api";

export interface StreamHandlers {
  onEvent: (event: AgentEvent) => void;
  onError?: (message: string) => void;
  onDone?: () => void;
}

export interface ParseResult {
  events: AgentEvent[];
  error: string | null;
}

const decoder = new TextDecoder();

/**
 * Parse a raw SSE body (ReadableStream<Uint8Array>) line-by-line.
 * Tolerant of CRLF, comment heartbeats, and malformed JSON payloads
 * (skipped with a console warning, stream continues).
 */
export async function readSSEStream(
  body: ReadableStream<Uint8Array>,
  handlers: StreamHandlers,
): Promise<void> {
  const reader = body.getReader();
  let buffer = "";
  let currentEvent = "";

  const dispatch = (dataLine: string) => {
    if (dataLine.startsWith("[")) {
      // Backend occasionally wraps events in an array (legacy framing).
      try {
        const parsed = JSON.parse(dataLine) as unknown;
        const list = Array.isArray(parsed) ? parsed : [parsed];
        for (const item of list) {
          if (item && typeof item === "object") {
            handlers.onEvent(item as AgentEvent);
          }
        }
      } catch {
        handlers.onError?.(`Malformed SSE payload: ${dataLine.slice(0, 120)}`);
      }
      return;
    }
    try {
      const payload = JSON.parse(dataLine) as unknown;
      if (payload && typeof payload === "object" && !("type" in payload) && currentEvent) {
        // The `event:` field names the frame (e.g. `done` with `data: {}`).
        (payload as Record<string, unknown>).type = currentEvent;
      }
      handlers.onEvent(payload as AgentEvent);
    } catch {
      handlers.onError?.(`Malformed SSE payload: ${dataLine.slice(0, 120)}`);
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Split on \n; tolerate \r\n.
      let nlIndex: number;
      while ((nlIndex = buffer.indexOf("\n")) !== -1) {
        let line = buffer.slice(0, nlIndex);
        buffer = buffer.slice(nlIndex + 1);
        if (line.endsWith("\r")) line = line.slice(0, -1);

        if (line === "") {
          // Blank line ends the current event frame.
          currentEvent = "";
          continue;
        }
        if (line.startsWith(":")) {
          continue; // comment heartbeat — ignore
        }
        if (line.startsWith("event:")) {
          currentEvent = line.slice("event:".length).trim();
          continue;
        }
        if (line.startsWith("data:")) {
          const dataLine = line.slice("data:".length).trim();
          if (dataLine === "") continue;
          dispatch(dataLine);
          void currentEvent; // envelope carries its own type
          continue;
        }
        // Unknown field — ignore.
      }
    }
    // Final buffer tail (no trailing newline).
    if (buffer.trim()) {
      const tail = buffer.trim();
      if (tail.startsWith("data:")) {
        dispatch(tail.slice("data:".length).trim());
      }
    }
  } catch (err) {
    handlers.onError?.(err instanceof Error ? err.message : "Stream read failed");
  }
}

/**
 * Parse a full SSE body into a collected result (test + non-streaming use).
 */
export async function parseSSEBody(body: ReadableStream<Uint8Array>): Promise<ParseResult> {
  const events: AgentEvent[] = [];
  let error: string | null = null;
  await readSSEStream(body, {
    onEvent: (ev) => events.push(ev),
    onError: (msg) => {
      error = msg;
    },
  });
  return { events, error };
}

/** UX vs debug classification (FE plan §6) — the dispatcher's split. */
export function isUserVisibleEvent(type: string): boolean {
  return USER_VISIBLE_EVENTS.has(type);
}

/** The named `done` terminal event. */
export function isDoneEvent(type: string): boolean {
  return type === "done";
}

/** The named `error` event. */
export function isErrorEvent(type: string): boolean {
  return type === "error";
}
