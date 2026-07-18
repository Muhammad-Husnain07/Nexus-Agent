# Nexus Console

Management console for the Nexus Agent platform — a React + TypeScript + MUI single-page application.

## Setup

```bash
npm install
```

## Development

Start the backend (`http://localhost:8000`) first, then:

```bash
npm run dev
```

## API Type Generation

Types in `src/lib/types.ts` are hand-written to match the backend. To auto-generate from the FastAPI OpenAPI schema:

```bash
npm run gen:api
```

This runs `openapi-typescript` against `http://localhost:8000/openapi.json` and writes to `src/api/schema.ts`. Requires the backend to be running.

## Environment Variables

Copy `.env.example` to `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend API base URL |
| `VITE_MUI_X_LICENSE_KEY` | _(optional)_ | MUI X Pro license key |
| `VITE_SENTRY_DSN` | _(optional)_ | Sentry DSN for error tracking |

## Build

```bash
npm run build
```

Output goes to `dist/`.

## Tests

```bash
npm test          # single run
npm run test:watch  # watch mode
```

## Docker

```bash
docker build -t nexus-console .
docker run -p 3000:80 nexus-console
```

Or run via docker-compose from the `nexus-agent` directory:

```bash
docker compose up -d nexus-console
```

## Project Structure

```
src/
├── api/           # API client and hooks
├── components/    # Shared UI components (layout, skeletons)
├── features/      # Feature modules (auth, chat, tools, sessions, etc.)
├── routes/        # Route pages (admin, memory, cost)
├── stores/        # Zustand stores (auth)
├── theme/         # MUI theme (extendTheme, themeStore)
├── lib/           # Utilities, types, API client
└── main.tsx       # App entry point with providers
```
