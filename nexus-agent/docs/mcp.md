# MCP Discovery Flow

Nexus Agent exposes its tool registry as a [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
server, so MCP-compatible clients (e.g. Claude Desktop, Cline) can discover and invoke
registered tools without going through the main `/api/v1/tools` REST endpoints.

## Architecture

```
                  ┌──────────────────────────────┐
                  │     MCP Client                │
                  │  (Claude Desktop, Cline, etc.) │
                  └──────────┬───────────────────┘
                             │  MCP Protocol (JSON-RPC over SSE)
                             ▼
                  ┌──────────────────────────────┐
                  │   FastAPI Application          │
                  │                                │
                  │  /mcp     ← FastApiMCP router  │
                  │  /api/v1/tools ← REST router   │
                  │                                │
                  │  ToolRegistry ← shared service │
                  └──────────────────────────────┘
```

## Endpoints

### MCP Server

The MCP server is automatically attached to the FastAPI application during startup
via `setup_mcp()` in `src/nexus/tools/mcp_server.py`. It exposes:

| MCP Method | Description |
|---|---|
| `tools/list` | Returns all enabled tools as MCP tool definitions |
| `tools/call` | Invokes a tool by name with the provided arguments |

The MCP server listens at the `/mcp` base URL using SSE transport.

### Discovery Flow

1. **Startup**: `FastApiMCP` introspects all FastAPI routes tagged with `"mcp"` and
   registers them as MCP tools.
2. **List**: An MCP client calls `tools/list` → the internal `/_mcp/tools/list` endpoint
   queries `ToolRegistry.list()` for all `enabled=true` tools.
3. **Call**: An MCP client calls `tools/call` with `{tool_name, arguments}` → the
   internal `/_mcp/tools/call` endpoint looks up the tool by name, resolves its
   endpoint URL and auth config, and makes the actual HTTP request.

### Internal MCP Routes

These routes are prefixed with `/_mcp` and tagged with `"mcp"` so `FastApiMCP` discovers them:

- `GET /_mcp/tools/list` — JSON list of `{name, description, input_schema}`
- `POST /_mcp/tools/call` — JSON body `{tool_name, arguments}` → executes the tool

## Usage with Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "nexus": {
      "url": "http://localhost:8000/mcp",
      "type": "sse"
    }
  }
}
```

Claude Desktop will then discover all enabled tools and allow Claude to invoke them.

## Security

- Tool execution via MCP respects the `auth_type` and `auth_ref` configured on each tool.
- The MCP server does **not** expose administrative operations (register, update, delete).
- MCP endpoints are protected by the same **AuthMiddleware** and **TenantMiddleware** as REST APIs — authentication inherits from the main FastAPI app. API keys and JWT tokens are passed via SSE transport headers by the MCP client.
- Sensitive operations still require HITL approval (`requires_approval` flag).

## Implementation Details

- Uses `fastapi_mcp.FastApiMCP` which auto-generates MCP tool definitions from
  FastAPI route metadata (path, method, docstring, query/body schemas).
- Tool execution is handled by `/_mcp/tools/call` which uses `httpx.AsyncClient`
  to proxy the request to the tool's configured `endpoint_url`.
- Error responses are returned as MCP content items with `is_error: true`.
