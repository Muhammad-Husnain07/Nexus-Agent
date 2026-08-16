/**
 * Run / state surface — GET /sessions/{id}/state, contract-validated at the
 * boundary (FE plan G4/G6: refresh reconstructs run state from the backend;
 * the browser must be disposable).
 */
import { get } from "./client";
import { agentStateSchema, parseContract } from "./contracts";
import type { AgentStateResponse } from "../types/api";

export async function getRunState(sessionId: string): Promise<AgentStateResponse> {
  const raw = await get<unknown>(`/sessions/${sessionId}/state`);
  return parseContract("AgentStateResponse", agentStateSchema, raw);
}
