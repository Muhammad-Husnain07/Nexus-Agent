import { describe, expect, it } from "vitest";

import { isUserVisibleEvent, parseSSEBody, readSSEStream } from "./stream";
import type { AgentEvent } from "../types/api";

function streamFrom(text: string): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(text));
      controller.close();
    },
  });
}

describe("SSE parser (single source of truth for chat + widget)", () => {
  it("parses event: + data: frames into typed envelopes", async () => {
    const events: AgentEvent[] = [];
    await readSSEStream(
      streamFrom(
        'event: final_response\ndata: {"type":"final_response","ts":"2026-01-01T00:00:00Z","payload":{"text":"hi","response_status":"SUCCESS"}}\n\n',
      ),
      { onEvent: (e) => events.push(e) },
    );
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("final_response");
    expect(events[0].payload).toMatchObject({ text: "hi" });
  });

  it("ignores comment heartbeats and unknown fields", async () => {
    const events: AgentEvent[] = [];
    await readSSEStream(
      streamFrom(
        ': keep-alive\nX-Unknown: foo\ndata: {"type":"error","ts":"t","payload":{"message":"boom"}}\n\n: keep-alive\n',
      ),
      { onEvent: (e) => events.push(e) },
    );
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("error");
  });

  it("tolerates CRLF line endings", async () => {
    const events: AgentEvent[] = [];
    await readSSEStream(
      streamFrom(
        'event: done\r\ndata: {}\r\n\r\n',
      ),
      { onEvent: (e) => events.push(e) },
    );
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("done");
  });

  it("skips malformed JSON without killing the stream", async () => {
    const events: AgentEvent[] = [];
    const errors: string[] = [];
    await readSSEStream(
      streamFrom(
        'data: {"type":"plan_created","ts":"t","payload":{}}\n\ndata: NOT-JSON\n\ndata: {"type":"done","ts":"t","payload":{}}\n\n',
      ),
      {
        onEvent: (e) => events.push(e),
        onError: (m) => errors.push(m),
      },
    );
    expect(events).toHaveLength(2);
    expect(errors).toHaveLength(1);
  });

  it("collects events + error via parseSSEBody", async () => {
    const result = await parseSSEBody(
      streamFrom('data: {"type":"done","ts":"t","payload":{}}\n\n'),
    );
    expect(result.events[0].type).toBe("done");
    expect(result.error).toBeNull();
  });

  it("handles a trailing data line without a final newline", async () => {
    const events: AgentEvent[] = [];
    await readSSEStream(
      streamFrom('data: {"type":"done","ts":"t","payload":{}}'),
      { onEvent: (e) => events.push(e) },
    );
    expect(events).toHaveLength(1);
  });

  it("classifies UX vs debug events", () => {
    expect(isUserVisibleEvent("final_response")).toBe(true);
    expect(isUserVisibleEvent("step_progress")).toBe(true);
    expect(isUserVisibleEvent("approval_checkpoint")).toBe(true);
    expect(isUserVisibleEvent("node_completed")).toBe(false);
    expect(isUserVisibleEvent("planner_timing")).toBe(false);
    expect(isUserVisibleEvent("map_degraded")).toBe(false);
    expect(isUserVisibleEvent("resolution_suppressed")).toBe(false);
  });
});
