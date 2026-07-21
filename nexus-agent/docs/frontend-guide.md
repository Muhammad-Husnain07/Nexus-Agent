# Frontend Developer Guide

## Overview

The Nexus Agent frontend is a **React 19 + TypeScript** single-page application
built with **Vite**. It provides a management console for registering, testing,
and monitoring tools, as well as a chat interface.

No auth — all pages are publicly accessible. User identity is auto-injected by
the backend.

HITL approvals appear inline in the chat SSE stream — no separate approval page.

### Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Build | Vite 8 | Fast HMR, optimized production builds |
| Language | TypeScript (strict) | Type safety across the entire app |
| UI | Tailwind CSS v4 + shadcn/ui | Utility-first styling, accessible components |
| State (server) | TanStack Query v5 | Caching, refetching, mutations for API data |
| State (client) | Zustand | UI preferences |
| Forms | React Hook Form + Zod | Schema-validated form inputs |
| HTTP | Axios | API client |
| Real-time | WebSocket / SSE | Chat streaming, agent events |
| DnD | @dnd-kit | JSON Schema property reordering |
| Editor | @monaco-editor/react | JSON Schema code editing |

---

## Project Structure

```
frontend/
├── src/
│   ├── App.tsx                — Routes + providers
│   ├── main.tsx               — Entry point
│   ├── index.css              — Tailwind v4 + CSS variables
│   ├── lib/                   — api.ts, query-client.ts, utils.ts, websocket.ts
│   ├── hooks/                 — TanStack Query hooks (use-tools-api, use-sessions, use-chat, use-memory)
│   ├── types/                 — tool.ts, session.ts, chat.ts, common.ts, api.ts
│   ├── routes/                — Page components per feature
│   │   ├── dashboard.tsx
│   │   ├── chat/index.tsx
│   │   ├── tools/index.tsx, [id].tsx, new.tsx
│   │   ├── sessions/index.tsx, [id].tsx
│   │   ├── memory/index.tsx
│   │   └── playground/index.tsx
│   └── components/
│       ├── Layout/            — dashboard-layout.tsx, Sidebar.tsx, top-nav.tsx
│       └── ui/                — button.tsx, card.tsx, input.tsx, badge.tsx
├── vite.config.ts
├── tsconfig.app.json          — strict: true
└── components.json            — shadcn/ui configuration
```

---

## Tool Builder Walkthrough

The **Tool Builder** (`/tools/new`) is a 7-step form wizard for registering
new tools. Each step validates its fields before allowing you to proceed.

### Step 1 — Basic Info

| Field | Description |
|-------|-------------|
| `name` | Lowercase, no spaces. Use `snake_case`. |
| `description` | Human-readable. The LLM reads this to decide tool relevance. Be specific. |
| `purpose` | When to use this tool. Helps the LLM understand context. |
| `category` | Functional group: `general`, `data`, `analytics`, `communication`, etc. |
| `tags` | Comma-separated keywords for filtering and semantic search. |

### Step 2 — API Configuration

Select the **tool type**:

- **HTTP API** (`http_api`): For REST, GraphQL, or any HTTP endpoint.
  - `endpoint_url`: Full URL including protocol (e.g., `https://api.example.com/v1/action`)
  - `http_method`: Color-coded selector (GET=green, POST=blue, PUT=orange, DELETE=red)
  - **Live URL validation**: Click "Test" to check if the endpoint is reachable

- **MCP Server** (`mcp`): For Model Context Protocol servers.
  - `mcp_server_url`: Base URL of the MCP server (e.g., `https://mcp.example.com`)

### Step 3 — Authentication

| Auth Type | Description | Header |
|-----------|-------------|--------|
| `none` | No authentication | — |
| `bearer` | Bearer token (OAuth2, JWT, PAT) | `Authorization: Bearer <token>` |
| `basic` | Base64-encoded credentials | `Authorization: Basic <base64>` |
| `api_key` | API key in custom header | `X-API-Key: <key>` |
| `oauth2` | OAuth2 bearer token | `Authorization: Bearer <token>` |

The **Auth Reference** field (`auth_ref`) connects to the credential vault.
Format: `env:VAR_NAME`, `vault:path/to/secret`, or `literal:value` (dev only).

### Step 4 & 5 — Input/Output Schema

Each schema uses the **JSON Schema Visual Editor**:

- **Tree view**: Add, edit, delete, and reorder properties via drag-and-drop
- **Property editor**: Set name, type, format, constraints, required flag, description, default value
- **Code toggle**: Switch between visual editor and raw JSON Schema (Monaco editor)
- **Preview**: See the generated JSON Schema in real-time
- **Import/Export**: Upload an existing JSON Schema file or download the current one

The schema must conform to **JSON Schema Draft 7**.

### Step 6 — Examples & Testing

After creating the tool, use the **[Test Playground](/test)** to verify it works.
Successful tests can be saved as examples.

### Step 7 — Risk & Approval

| Setting | Options | Description |
|---------|---------|-------------|
| Requires Approval | Toggle | If on, every invocation needs HITL approval |
| Risk Level | Low / Medium / High | Medium+ triggers HITL by default |
| Rate Limit | Number | Max requests per minute (null = unlimited) |
| Idempotent | Toggle | Safe to retry on failure |

### Preview Panel

Click **"Preview"** to see the full tool definition as JSON. This shows exactly
what will be sent to the API when you click "Create Tool".

---

## Testing Playground

The **Test Playground** (`/test`) lets you run real HTTP calls against your
registered tools without going through the agent.

### Workflow

1. **Select a tool** from the dropdown
2. The form auto-generates from the tool's `input_schema`
3. Fill in the parameters
4. Optionally enter **Thought** (agent reasoning) for the T→A→O visualization
5. Click **Run Test**
6. View the response in JSON, Raw, or Headers tabs

### Thought → Action → Observation

This three-column visualization mirrors the ReAct agent loop:

- **Thought**: Your reasoning about why this tool was selected
- **Action**: The tool name and arguments (auto-populated)
- **Observation**: The parsed response

Use this to debug how the agent would perceive the tool call cycle.

### Utilities

- **Copy cURL**: Generates a `curl` command equivalent of the request
- **Export JSON**: Downloads the response as a JSON file
- **Save as Example**: Prepopulates Step 6 of the Tool Builder (coming soon)

---

## Styling Customization

The UI uses **Tailwind CSS v4** with CSS custom properties for theming.

### CSS Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `--background` | `oklch(1 0 0)` | Page background |
| `--foreground` | `oklch(0.145 0 0)` | Text color |
| `--primary` | `oklch(0.205 0.042 265.755)` | Primary brand color |
| `--primary-foreground` | `oklch(0.985 0 0)` | Text on primary |
| `--radius` | `0.625rem` | Border radius |

### Dark Mode

The `.dark` class on `<html>` toggles dark theme variables. Add it via:

```tsx
document.documentElement.classList.toggle('dark')
```

### Custom Themes

Override variables in your CSS:

```css
:root {
  --primary: oklch(0.5 0.2 200);
  --radius: 0.5rem;
}
```

---

## Building for Production

```bash
# Main console app
npm run build
# Output: dist/
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_URL` | `/api` | Backend API base URL (proxied in dev) |
| `VITE_WS_URL` | `ws://localhost:8000/ws` | WebSocket endpoint |

Copy `.env.example` to `.env` and fill in your values:

```env
VITE_API_URL=https://api.nexus.example.com
VITE_WS_URL=wss://api.nexus.example.com/ws
```
