<#
.SYNOPSIS
    Start Nexus Agent development servers (Windows alternative to `make dev`).
.DESCRIPTION
    Starts the backend (uvicorn) and frontend (vite) dev servers with hot-reload.
    Run from the repo root or nexus-agent/ directory.

.PARAMETER BackendOnly
    Start only the backend server.
.PARAMETER FrontendOnly
    Start only the frontend server.
.PARAMETER NoSeed
    Skip database seeding on startup.
.PARAMETER Help
    Show this help message.

.EXAMPLE
    .\nexus-agent\scripts\dev.ps1              # start both servers
    .\nexus-agent\scripts\dev.ps1 -BackendOnly  # backend only
    .\nexus-agent\scripts\dev.ps1 -FrontendOnly # frontend only
#>

param(
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [switch]$NoSeed,
    [switch]$Help
)

if ($Help) {
    Get-Help $PSCommandPath -Detailed
    exit
}

$ROOT = Resolve-Path "$PSScriptRoot\..\.."
$BACKEND = "$ROOT\nexus-agent"
$FRONTEND = "$ROOT\frontend"

# ── Check prerequisites ──────────────────────────────────────────────────────

function Check-Command($cmd, $name) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        Write-Host "  ✅ $name" -ForegroundColor Green
        return $true
    } else {
        Write-Host "  ❌ $name — install from https://python.org or https://nodejs.org" -ForegroundColor Red
        return $false
    }
}

Write-Host "`n🔍 Checking prerequisites..." -ForegroundColor Cyan
$py = Check-Command "python" "Python 3.12+"
$node = Check-Command "node" "Node.js 20+"

if (-not $py) { exit 1 }
if (-not $node -and -not $FrontendOnly) { exit 1 }

# ── Ensure .env exists ───────────────────────────────────────────────────────

if (-not (Test-Path "$BACKEND\.env")) {
    if (Test-Path "$BACKEND\.env.example") {
        Copy-Item "$BACKEND\.env.example" "$BACKEND\.env"
        Write-Host "  📝 Created .env from .env.example — edit it before starting" -ForegroundColor Yellow
    } else {
        Write-Host "  ❌ No .env or .env.example found in nexus-agent/" -ForegroundColor Red
        exit 1
    }
}

# ── Install dependencies if needed ───────────────────────────────────────────

if (-not (Test-Path "$BACKEND\.venv")) {
    Write-Host "`n📦 Installing backend dependencies..." -ForegroundColor Cyan
    Push-Location $BACKEND
    & "uv" sync 2>$null
    if (-not $?) {
        & "python" -m venv .venv
        &.venv\Scripts\pip install -e ".[dev]" 2>$null
    }
    Pop-Location
}

if (-not (Test-Path "$FRONTEND\node_modules") -and -not $BackendOnly) {
    Write-Host "`n📦 Installing frontend dependencies..." -ForegroundColor Cyan
    Push-Location $FRONTEND
    & "npm" install 2>$null
    Pop-Location
}

# ── Run migrations ───────────────────────────────────────────────────────────

Write-Host "`n🗄️  Running database migrations..." -ForegroundColor Cyan
Push-Location $BACKEND
& "uv" run alembic upgrade head
if (-not $?) {
    Write-Host "  ⚠️  Migrations failed — make sure PostgreSQL is running" -ForegroundColor Yellow
}
Pop-Location

# ── Seed demo data ───────────────────────────────────────────────────────────

if (-not $NoSeed) {
    Write-Host "`n🌱 Seeding demo data..." -ForegroundColor Cyan
    Push-Location $BACKEND
    & "uv" run python scripts/seed.py --no-embed 2>$null
    Pop-Location
}

# ── Start servers ────────────────────────────────────────────────────────────

$jobs = @()

if (-not $FrontendOnly) {
    Write-Host "`n🚀 Starting backend (port 8000)..." -ForegroundColor Cyan
    $jobs += Start-Job -ScriptBlock {
        param($dir)
        Set-Location $dir
        & "uv" run uvicorn nexus.main:create_app --factory --reload --host 0.0.0.0 --port 8000
    } -ArgumentList $BACKEND
}

if (-not $BackendOnly) {
    Write-Host "🚀 Starting frontend (port 5173)..." -ForegroundColor Cyan
    $jobs += Start-Job -ScriptBlock {
        param($dir)
        Set-Location $dir
        & "npm" run dev
    } -ArgumentList $FRONTEND
}

Write-Host "`n"
Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║     Nexus Agent is starting up            ║" -ForegroundColor Green
Write-Host "╠══════════════════════════════════════════╣" -ForegroundColor Green
Write-Host "║  Frontend:  http://localhost:5173         ║" -ForegroundColor Green
Write-Host "║  Backend:   http://localhost:8000         ║" -ForegroundColor Green
Write-Host "║  API docs:  http://localhost:8000/docs    ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Green
Write-Host "`nPress Ctrl+C to stop both servers.`n" -ForegroundColor Gray

# Wait for either job to finish (or Ctrl+C)
try {
    Wait-Job -Job $jobs -Any | Out-Null
} finally {
    Write-Host "`nShutting down..." -ForegroundColor Yellow
    $jobs | Stop-Job -PassThru | Remove-Job
}
