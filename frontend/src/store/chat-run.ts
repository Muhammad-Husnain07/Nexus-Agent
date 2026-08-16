/**
 * Live chat-run state (Zustand, ephemeral — NOT persisted; the browser is
 * disposable and reconstructs from the backend on refresh).
 */
import { create } from "zustand";

import {
  createRunLifecycle,
  reduceRunEvent,
  transitionRun,
  type RunLifecycle,
  type RunPhase,
} from "../api/lifecycle";
import type { AgentEvent } from "../types/api";

interface ChatRunState {
  sessionId: string | null;
  lifecycle: RunLifecycle;
  streaming: boolean;
  /** True after refresh while the server-side run is still running. */
  observing: boolean;
  setEvent: (ev: AgentEvent) => void;
  setPhase: (phase: RunPhase) => void;
  setStreaming: (streaming: boolean) => void;
  setObserving: (observing: boolean) => void;
  setApprovalExpiry: (expiresAtEpochSeconds: number | null) => void;
  restore: (sessionId: string, lifecycle: RunLifecycle, observing: boolean) => void;
  reset: () => void;
}

export const useChatRunStore = create<ChatRunState>((set) => ({
  sessionId: null,
  lifecycle: createRunLifecycle(),
  streaming: false,
  observing: false,
  setEvent: (ev) => set((s) => ({ lifecycle: reduceRunEvent(s.lifecycle, ev) })),
  setPhase: (phase) => set((s) => ({ lifecycle: transitionRun(s.lifecycle, phase) })),
  setStreaming: (streaming) => set({ streaming }),
  setObserving: (observing) => set({ observing }),
  setApprovalExpiry: (expiresAtEpochSeconds) =>
    set((s) => ({
      lifecycle: {
        ...s.lifecycle,
        approvalExpiresAt:
          expiresAtEpochSeconds != null ? expiresAtEpochSeconds * 1000 : null,
      },
    })),
  restore: (sessionId, lifecycle, observing) => set({ sessionId, lifecycle, observing, streaming: false }),
  reset: () =>
    set({ sessionId: null, lifecycle: createRunLifecycle(), streaming: false, observing: false }),
}));
