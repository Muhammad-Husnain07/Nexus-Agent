# Frontend–Backend E2E Integration Plan

Status: PLAN (not yet implemented) — 2026-08-16
Backend: frozen orchestration at `548c438` (PH-0..PH-6 hardening complete).
Rule: **the frontend consumes existing backend contracts; it never duplicates
orchestration logic.** Backend contracts in this document were extracted
directly from source (see `docs/audits/NEXUS_COMPLETE_PROJECT_AUDIT-2026-08-16.txt`
for the backend audit; the contract details below cite `nexus-agent/src/nexus/**`).

---

## 1. Existing frontend structure

| Area | State (evidence) |
|---|---|
| Stack | React 19.2.7, React Router v7 (lazy routes), TanStack Query ^5, Zustand ^5, Tailwind v4, shadcn primitives, sonner, lucide-react, axios ^1.18 (`frontend/package.json`) |
| Routing | `/dashboard /chat /tools[/new/:id/edit] /sessions[/:id] /memory /settings /test` wired in `App.tsx`; **`/workflows`, `/tasks`, `/widget` pages exist but are NOT routed (dead)** |
| Server state | QueryClient (staleTime 30s, retry 3, no 4xx retry) `src/lib/query-client.ts` |
| Client state | `useThemeStore` (persisted), `useChatStore` (activeSessionId, streaming — not persisted), `useSidebarStore` |
| API client | axios `baseURL /api/v1`, 30s timeout, response-logging interceptor only (`src/lib/api.ts`) — **no request interceptor (auth), no error normalization** |
| Chat streaming | **Raw `fetch` + hand-rolled SSE parser** duplicated in `routes/chat/index.tsx:40-70` and `components/embed/chat-widget.tsx:78-87`; handles `final_response`, `tool_call_started/completed`, `plan_created`, `reflection_result`, `error`, `done` (console) + `approval_checkpoint` (widget only) |
| WebSocket | Backend endpoint + `WebSocketManager` + `useAgentEvents` hook exist — **zero consumers (dead)** |
| Tests | 3 vitest files + 2 playwright smoke tests; **vitest/jsdom/@playwright/test absent from package.json + lockfile → not runnable on clean checkout; no CI workflow** |
| Docs | `frontend/README.md` is the unmodified Vite template; sidebar claims "5-node LangGraph" (backend is 19-node) |

## 2. Existing backend endpoints (the contracts we build against)

Full reference with field names: `docs/audits/` extraction; essentials:

- **Chat**: `POST /api/v1/sessions/{id}/chat` — body `{message (1..32000), attachments? (≤10), stream? (default true)}`; SSE frames `event: <type>` + `data: <json envelope {type, ts, payload}>`; `: keep-alive` comments every 10s; terminal `done`; error frame `error {message}`; headers `Cache-Control: no-cache` + `X-Accel-Buffering: no`. JSON mode (`stream:false`) → `ChatResponse {session_id, final_response, requires_approval, approval_payload, interrupted, error, events, request_id}`.
- **Run state**: `GET /sessions/{id}/state` → `{session_id, status (running|completed|cancelled|timed_out|interrupted|failed), current_node, final_response}`.
- **SSE event inventory** (all typed `{type, ts, payload}`):
  `node_completed {node, duration_ms, has_output, cost_usd, retries}`; `final_response {text, cost_usd, latency_ms, response_status (SUCCESS|PARTIAL_SUCCESS|EXECUTION_FAILED|PLANNING_FAILED), coverage_breakdown}`; `plan_created {steps, waves, strategy, estimated_cost_usd, estimated_latency_ms}` + `step_progress {step, status, text, tool_name}` (statuses queued|running|waiting|approval|retrying|completed|failed|cancelled|skipped); `tool_call_completed {tool_name, status, data (masked), error, task_id, duration_ms, retries, cached}`; `error {message}`; `routing_decision {decision, reason, candidates}`; `execution_completed {status, final_response, cost_usd, duration_ms}`; `approval_checkpoint {message, tools, policy, context, options}`; `intent_extracted`; `tool_selected`; `clarification_question {question, slots_filled}`; `map_degraded {degradations}`; `resolution_suppressed {suppressions}`; `planner_timing {latency_ms, chunk_timing}`; `workflow_*` (composing/step/input/paused/cancelled/completed); `validation_progress`; `artifact_produced`; `reflection_result`.
- **WebSocket** `/sessions/{id}/ws`: auth-before-accept (`?token=` or Bearer; close 4401/4403), server heartbeat 30s, receive-timeout 90s; client frames `{type: message|chat|cancel|ping}`; server sends every AgentEvent envelope; error frame `{type:error, payload:{message}}`.
- **REST**: sessions CRUD+fork+rename+messages (`SessionRead/MessageRead`; message `content` is a **dict** `{text: ...}`); memory (bare list, canonical kinds episodic|semantic|procedural); tasks (`TaskCreate` + task dict with statuses pending|queued|running|paused|completed|failed|cancelled + progress/result/error_message); workflows (definitions CRUD + activate/deactivate + instances, `version` bumps); long-running; tools (CRUD + test `ToolResult` + versions/diff + search); learning (invocations + provider reliability); projects (no ownership checks — flag).
- **Errors**: middleware `{error: {code, message, request_id}}`; common `HTTPException` → `{detail}`; 429 `{detail, error_code: RATE_LIMITED}` + Retry-After; drain 503 SHUTTING_DOWN; SSE/WS error payloads are `{message}`. Run-status failure values: `timed_out|interrupted|cancelled|failed`; `_response_status` values above.
- **Auth**: `auth.mode=none` default (anonymous); `api_key` → `X-API-Key`; `jwt` → `Authorization: Bearer` (sub|user_id, roles). Production boot gate refuses `none`.
- **CORS**: `cors_origins` default `["*"]`; compose wiring `nexus-console → nexus-agent:8000`; vite dev proxy `/api` + `/ws` → WSL2 backend.

## 3. Mismatches / gaps

| # | Gap | Evidence | Severity |
|---|---|---|---|
| G1 | Chat + widget call `fetch()` directly (no client interceptors, no timeout, no error normalization) | `routes/chat/index.tsx:226`, `chat-widget.tsx:132,177` | High |
| G2 | Console chat ignores `approval_checkpoint` (only the widget handles it) — approvals pause silently in the console | event handling sets above | High |
| G3 | Console chat ignores `clarification_question`, `tool_selected`, `node_completed`, `map_degraded`, `resolution_suppressed`, `planner_timing`, `validation_progress`, `artifact_produced`, `workflow_*`, `routing_decision` | chat handler list | High |
| G4 | `GET /sessions/{id}/state` never consumed → no run-status reconstruction after refresh | grep: zero callers | High |
| G5 | WebSocket fully built on both sides, unconnected | `lib/websocket.ts`, `use-agent-events.ts` dead | Medium |
| G6 | Type drift: `ApiError {code,message,details}` vs backend `{error:{code,message,request_id}}`; `ChatMessage.content` typed `string` vs backend dict `{text}`; `Tool` missing 8 fields; no types for `ChatRequest/AgentStateResponse/ToolSearchResult/WorkflowInstance` | `src/types/*` vs `api/schemas.py`, `tools/schemas.py` | High |
| G7 | Workflows/Tasks/Widget pages + hooks dead (no routes) | `App.tsx:53-66` | Medium |
| G8 | Test tooling absent from package.json/lockfile; no CI | package.json, lockfile grep | High |
| G9 | No auth mechanism (headers/token/login) — must be added for `api_key`/`jwt` modes | no interceptor | Medium (mode=none today) |
| G10 | `build:embed` script missing (widget studio references it) | `widget/index.tsx:222` | Low |
| G11 | Decorative controls: settings toggles inert, top-nav search inert, dashboard memory stat hardcoded; stale "5-node" claims | settings.tsx, top-nav.tsx, dashboard.tsx, Sidebar.tsx:67 | Low |
| G12 | `approval_checkpoint` uses `tools` field (typed model says `pending_tools`); `ChatResponse.request_id` never populated; `state` endpoint does not expose `_approval_pending` after refresh | backend extraction | Low (client must track pending locally) |
| G13 | Chat history fidelity: past turns lose plan/tool/reflection data; messages fetched once at 100/page, no pagination | `chat/index.tsx:167-176` | Medium |

## 4. Missing API contracts (backend-side, small)

1. (Optional) `GET /sessions/{id}/state` could include `approval_pending: {...} | null` (+ `requested_at`/`expires_at`) so the UI can reconstruct an open approval after refresh — **client-side tracking is the fallback; do not block on this**.
2. (Optional) `GET /sessions/{id}/events` (paginated `execution_events`) for the developer console timeline after the fact — today only live SSE + `InvocationOutcome` + `ToolExecution` rows exist (no public read endpoint for execution events).
3. Nothing else: every UI feature maps to an existing endpoint (Section 2).

## 5. Missing frontend routes (to build)

| Route | Purpose | Backend surface |
|---|---|---|
| `/tasks` (+ `/tasks/:id`) | Durable background-task lifecycle (survives refresh) | `GET/POST /tasks`, `GET /tasks/{id}`, pause/resume/cancel |
| `/workflows` (+ detail) | Workflow-definition CRUD + activation + instances | `/workflows*` |
| `/approvals` | Pending/expired approval ledger (client-tracked, per session) | `approval_checkpoint` events + resume via chat |
| `/dev` (developer console) | IntentGraph, plan, resolution/suppressions, binding, validation, execution DAG/waves, artifacts, evidence, latency, model calls | SSE events (`planner_timing`, `resolution_suppressed`, `map_degraded`, `node_completed`, `validation_progress`, `artifact_produced`, `tool_call_completed`), `GET state`, `GET /tools/retrieve` + `/tools/resolution-index` (debug probes), `GET /learning/workflows` |
| `/login` (future) | api_key/jwt credential entry | auth modes |
| Wire `/widget` studio | embed-snippet generator (needs `build:embed` script restored) | n/a |

## 6. State architecture

- **Server state (source of truth) = TanStack Query**: sessions, messages, tools, memory, tasks, workflows, run state. Every query keys off `session_id`/`id`; `refetchInterval` only for durable polls (tasks 5s while any running/pending; state 3s while `running`).
- **Client state = Zustand, minimal and non-authoritative**:
  - `useChatStore`: activeSessionId, streamAbortController, event-log accumulator for the CURRENT live run (ephemeral), pending-approval tracker (sessionId → {tools, policy, requested_at, expires_at}).
  - `useThemeStore`, `useSidebarStore` (existing).
- **Browser is never the source of truth**: on refresh, reconstruct from `GET /sessions/{id}/state` + `GET /sessions/{id}/messages` + `GET /tasks`; live run continues server-side (SSE/WS dropped only disconnects the observer).
- **Error/loading/empty**: every query gets `isLoading` skeleton, `isError` branch (rendered from the normalized client error), and `isEmpty` state; global toast reserved for mutations.

## 7. Streaming architecture (streaming-first chat)

1. **One shared SSE client** `src/api/stream.ts`: fetch-stream (`Accept: text/event-stream`), strict SSE parser (event/data/comment lines; comment = heartbeat, ignored), typed event dispatch table (Section 2 inventory), AbortSignal, on-close/on-error hooks, optional auto-reconnect for the observer (POST replays are NOT retried blindly — the graph continues server-side; reconnect = reattach + refetch state).
2. **Event → UI state machine** (the lifecycle the user sees):
   `request sent → intent/plan events → "Planning"` → `plan_created → "Validating"` → `step_progress queued/running/approval/retrying/completed → "Executing N operations"` (per-tool rows with ✓/✗/… states, cached badge) → `artifact_produced` → `"Preparing answer"` → `final_response` → `execution_completed → "Complete"`; any `error`/budget event → failure state with the exact message; `TIMED_OUT/INTERRUPTED` surfaced distinctly; `approval_checkpoint` → paused state; `clarification_question` → input prompt; `map_degraded`/`resolution_suppressed`/`planner_timing`/`validation_progress`/`node_completed` → developer-console timeline + optional "info" chips (not raw internals in user UI).
3. **Status mapping** (never "Something went wrong"): `PLANNING_FAILED`/`EXECUTION_FAILED`/`PARTIAL_SUCCESS`/`TIMED_OUT`/`CANCELLED`/`REQUIRES_APPROVAL`/`CLARIFICATION_REQUIRED`/`CONVERSATIONAL` → dedicated banners (e.g., partial: "3 of 4 operations succeeded — the university lookup could not be completed." from step rows + error text).
4. **WebSocket as the second transport** (same typed dispatcher, `WebSocketManager` revived): used when WS is available for cancel (`{type:"cancel"}`) + live events; SSE remains the default chat path. One dispatcher, two sources.
5. **Timeline widget**: vertical stepper with per-phase chips (routing → planning → validation → execution → synthesis → memory); tool rows grouped under "Executing"; durations from `node_completed.duration_ms`/`tool_call_completed.duration_ms`.

## 8. Authentication flow

- Add an axios **request interceptor** (`src/lib/api.ts`): attaches `Authorization: Bearer <token>` or `X-API-Key` from a credentials store (localStorage, keys `nexus_auth_token`/`nexus_api_key`), always sends `X-Request-Id` (crypto.randomUUID) for correlation with `request_id` in errors.
- Response interceptor normalizes ALL errors to `ApiError {code, message, request_id, status}` (reads `error.code/message/request_id`, then `detail`, then message) — fixes G6/G8.
- `/login` route (future, only when backend `auth.mode != none`): api-key/JWT token entry; WS `?token=` for the socket; 401 interceptor → login redirect; 403 ownership errors → explicit "session belongs to another user".
- No backend changes needed (mode stays `none` locally).

## 9. Task & approval flow

**Tasks**: `/tasks` page with status filter; per-task card: type, session, status badge, progress bar (from `progress`), attempts, `error_message` disclosure, pause/resume/cancel actions; 5s refetch while active; detail drawer. Chat page shows an inline "running in background" banner when `execution_completed.status = queued` or a task row for the session appears (task API is the durable surface after refresh — G4/G7).

**Approvals**: on `approval_checkpoint`: render a decision card — operation (tools + method + inputs from `context`/`tools`), policy, options, and an **expiry countdown** computed from `requested_at + approval_expiry_s` (client stores `requested_at`; server enforces expiry — on expiry the user's next message gets the cancellation response, and the card must flip to "expired — re-send your request"). Approve/Reject/Cancel/Modify/Clarify are plain chat messages (the resume is conversational — no separate endpoint); the UI sends the intent text. Post-refresh reconstruction: pending approval tracked client-side per session; `GET state` does not expose it (G12) — a "pending approval" chip on the session card uses the client tracker.

## 10. End-to-end test matrix

| # | Scenario | Transport | Coverage |
|---|---|---|---|
| E1 | Login (api_key mode) → create session → send query → full SSE lifecycle → final response | SSE | auth + stream + render |
| E2 | Multi-intent query: plan shows N operations, execution rows all ✓, response cites all artifacts | SSE | plan/step UI |
| E3 | Parallel branches: wave info correct, tool rows in-flight | SSE | timeline |
| E4 | Approval: checkpoint → decision card → approve → stream continues; reject → cancellation; expired (monkeypatched expiry) → re-request | SSE | approval UX |
| E5 | Partial failure: 3/4 ✓, 1 ✗ with error → PARTIAL_SUCCESS banner (not generic error) | SSE | status mapping |
| E6 | Background task: threshold query → "running in background" → `/tasks` shows queued→running→completed; **refresh during run** → state/task reconstruction | SSE + REST | durability |
| E7 | Cancel: WS `cancel` mid-run → cancelled status | WS | cancel |
| E8 | Timeout: budget-exceeded query → TIMED_OUT banner (exact message) | SSE | status mapping |
| E9 | Clarification: `clarification_question` → input prompt → resume | SSE | clarifications |
| E10 | Developer console: planner_timing + resolution_suppressed + map_degraded + node durations render in /dev timeline | SSE | dev UI |
| E11 | Session history: refresh → messages/plan/state reconstructed; messages paginated | REST | durability |
| E12 | Memory page: list/search/delete; workflow + tasks CRUD round-trips | REST | CRUD |

Unit (vitest, tooling must be added to package.json): SSE parser (comments/CRLF/malformed JSON/done), event dispatcher mapping, status-mapping function, error normalizer, stores. Playwright: E1/E4/E6 as the three critical browser-level flows.

## 11. Implementation order

1. **Foundations (contracts first)**: add test tooling (vitest, jsdom, @testing-library, @playwright/test) to package.json + lockfile; fix types (`ApiError`, `ChatMessage.content` dict, add missing interfaces); centralized `src/api/client.ts` (axios interceptors: auth, request-id, error normalization) + `src/api/stream.ts` (shared SSE parser/dispatcher) + `src/api/{sessions,chat,tasks,workflows,memory,tools,runs}.ts`; CI workflow (lint, typecheck, vitest, build; e2e nightly).
2. **Streaming-first chat**: rewire `routes/chat` to the shared stream client; full event handling (approval card, clarification, partial banner, execution timeline); run-status reconstruction via `GET state` on mount/refresh; revive WebSocket transport + cancel.
3. **Durable tasks + approvals**: route + UI for `/tasks`; task polling; approval tracker + expiry countdown; background-run banner.
4. **Workflows + memory polish**: wire `/workflows` (existing page, now routed); memory search/pagination; fix decorative settings/top-nav/dashboard; wire `/widget` studio (restore `build:embed`).
5. **Developer console** (`/dev`): timeline from the observability events + debug probes + `GET /learning/workflows`; latency/suppression/map-degradation views.
6. **E2E suites**: vitest units during 1–2; Playwright E1/E4/E6; nightly matrix (Section 10).
7. **Auth polish** (only if backend moves off `auth.mode=none`): `/login`, token storage, 401 handling, WS token.

Each step lands with its tests; no backend orchestration changes (contracts are the source of truth). Candidate backend additions (Section 4) are strictly additive and non-blocking.
