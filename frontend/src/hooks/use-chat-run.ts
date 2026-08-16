/**
 * useChatRun — wires the chat transport (src/api/chat.ts) + shared SSE
 * dispatcher (src/api/stream.ts) + lifecycle reducer into the store.
 * This is the ONLY place a component drives a chat run.
 */
import { useCallback, useRef } from "react";

import { cancelRun, openChatStream } from "../api/chat";
import {
  createRunLifecycle,
  phaseFromRunStatus,
  reduceRunEvent,
  transitionRun,
} from "../api/lifecycle";
import { getRunState } from "../api/runs";
import { readSSEStream } from "../api/stream";
import { useChatRunStore } from "../store/chat-run";

export function useChatRun() {
  const store = useChatRunStore();
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(
    async (sessionId: string, message: string): Promise<void> => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      store.setStreaming(true);
      store.setObserving(false);
      store.restore(sessionId, createRunLifecycle(), false);
      try {
        const res = await openChatStream(sessionId, { message }, controller.signal);
        if (!res.body) {
          store.setStreaming(false);
          return;
        }
        await readSSEStream(res.body, {
          onEvent: (ev) => store.setEvent(ev),
          onError: (msg) =>
            store.setEvent({
              type: "error",
              ts: new Date().toISOString(),
              payload: { message: msg },
            }),
          onDone: () => store.setStreaming(false),
        });
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          store.setPhase("cancelled");
        } else {
          const message = err instanceof Error ? err.message : "Request failed";
          store.setEvent({
            type: "error",
            ts: new Date().toISOString(),
            payload: { message },
          });
        }
        store.setStreaming(false);
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
      }
    },
    [store],
  );

  /** Cancel: WS cancel first (backend stops the run), abort as fallback. */
  const cancel = useCallback(
    async (sessionId: string): Promise<void> => {
      const acknowledged = await cancelRun(sessionId);
      abortRef.current?.abort();
      store.setStreaming(false);
      store.setObserving(false);
      store.setPhase(acknowledged ? "cancelled" : "cancelled");
    },
    [store],
  );

  /**
   * Refresh/reconnect reconstruction — the browser is an observer; the
   * server owns the run. GET state -> reconstruct phase/approval; while
   * `running`, the caller polls (see useRunReconstruction).
   */
  const reconstruct = useCallback(
    async (sessionId: string): Promise<{ observing: boolean }> => {
      try {
        const state = await getRunState(sessionId);
        const lifecycle = createRunLifecycle();
        lifecycle.phase = phaseFromRunStatus(state.status);
        if (state.final_response) {
          lifecycle.finalText = state.final_response;
          lifecycle.responseStatus = null; // reconstructed from messages
        }
        if (state.approval_pending) {
          lifecycle.phase = "approval";
          lifecycle.approval = {
            message: state.approval_pending.message,
            tools: state.approval_pending.tools,
            policy: state.approval_pending.policy,
            context: state.approval_pending.context,
            options: ["approve", "reject", "cancel", "modify", "clarify"],
          };
          lifecycle.approvalExpiresAt =
            state.approval_pending.expires_at != null
              ? state.approval_pending.expires_at * 1000
              : null;
        }
        const observing = state.status === "running";
        store.restore(sessionId, lifecycle, observing);
        return { observing };
      } catch {
        return { observing: false };
      }
    },
    [store],
  );

  return {
    lifecycle: store.lifecycle,
    streaming: store.streaming,
    observing: store.observing,
    send,
    cancel,
    reconstruct,
    reset: store.reset,
    setPhase: store.setPhase,
    setEvent: store.setEvent,
  };
}

/** Poll run state while observing a server-side run after refresh. */
export function useRunReconstruction(sessionId: string | null, active: boolean, onDone?: () => void) {
  const store = useChatRunStore();
  const doneRef = useRef(false);

  return useCallback(async () => {
    if (!sessionId || !active || doneRef.current) return;
    try {
      const state = await getRunState(sessionId);
      if (state.status === "running") {
        store.setObserving(true);
        return;
      }
      doneRef.current = true;
      store.setObserving(false);
      store.setPhase(phaseFromRunStatus(state.status));
      if (state.final_response) {
        store.setEvent({
          type: "final_response",
          ts: new Date().toISOString(),
          payload: { text: state.final_response, response_status: null, coverage_breakdown: {} },
        });
      }
      onDone?.();
    } catch {
      /* no state yet */
    }
  }, [sessionId, active, store, onDone]);
}
