"""Interactive setup wizard — walks through project configuration.

Usage:
    uv run python scripts/setup.py        # interactive
    uv run python scripts/setup.py --auto  # non-interactive (uses defaults)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
ENV_FILE = PROJECT_ROOT / ".env"


def _ask(question: str, default: str = "") -> str:
    """Ask a question and return the answer."""
    if default:
        prompt = f"{question} [{default}]: "
    else:
        prompt = f"{question}: "
    answer = input(prompt).strip()
    return answer if answer else default


def _check_command(cmd: str) -> bool:
    """Check if a command is available."""
    return shutil.which(cmd) is not None


def check_prerequisites() -> bool:
    print("\n🔍 Checking prerequisites...")
    ok = True

    python_ok = _check_command("python") or _check_command("python3")
    if python_ok:
        print("  ✅ Python")
    else:
        print("  ❌ Python — install Python 3.12+ from https://python.org")
        ok = False

    uv_ok = _check_command("uv")
    if uv_ok:
        print("  ✅ uv (package manager)")
    else:
        print("  ⚠️  uv not found — will use pip. Install: https://docs.astral.sh/uv/")

    node_ok = _check_command("node")
    if node_ok:
        print("  ✅ Node.js")
    else:
        print("  ❌ Node.js — install Node 20+ from https://nodejs.org")
        ok = False

    docker_ok = _check_command("docker")
    if docker_ok:
        print("  ✅ Docker (optional, for PostgreSQL/Redis)")
    else:
        print("  ⚠️  Docker not found — will use existing services if available")

    return ok


def pick_llm_provider() -> dict[str, str]:
    print("\n🤖 Select your LLM provider:")
    print("  1) Ollama (local, free, runs on your machine)")
    print("  2) OpenAI (paid API key required)")
    print("  3) Gemini (free tier available)")
    print("  4) OpenRouter (multi-model, free tier available)")
    print("  5) Other (custom OpenAI-compatible endpoint)")

    choice = _ask("Choice", "1")

    providers = {
        "1": {
            "provider": "ollama",
            "model": "ollama/qwen2.5:7b",
            "embed_model": "ollama/nomic-embed-text",
            "api_key": "",
            "base_url": "http://localhost:11434",
        },
        "2": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "embed_model": "text-embedding-3-small",
            "api_key": "sk-...",
            "base_url": "",
        },
        "3": {
            "provider": "gemini",
            "model": "gemini/gemini-2.0-flash-lite",
            "embed_model": "gemini/gemini-embedding-001",
            "api_key": "AI...",
            "base_url": "",
        },
        "4": {
            "provider": "openrouter",
            "model": "openrouter/qwen/qwen3-coder:free",
            "embed_model": "openrouter/text-embedding-3-small",
            "api_key": "sk-or-v1-...",
            "base_url": "https://openrouter.ai/api/v1",
        },
    }

    if choice in providers:
        cfg = providers[choice].copy()
        if choice == "1":
            url = _ask("Ollama base URL", cfg["base_url"])
            cfg["base_url"] = url
            cfg["provider"] = "ollama"
        elif choice == "2":
            cfg["api_key"] = _ask("OpenAI API key", cfg["api_key"])
        elif choice == "3":
            cfg["api_key"] = _ask("Gemini API key", cfg["api_key"])
        elif choice == "4":
            cfg["api_key"] = _ask("OpenRouter API key", cfg["api_key"])
    else:
        cfg = {
            "provider": "openai",
            "model": _ask("Model name", "gpt-4o-mini"),
            "embed_model": _ask("Embedding model", "text-embedding-3-small"),
            "api_key": _ask("API key", "sk-..."),
            "base_url": _ask("Base URL (leave empty for default)", ""),
        }

    return cfg


def generate_env(cfg: dict[str, str]) -> None:
    print("\n📝 Generating .env file...")

    provider_json = []
    if cfg["provider"] == "ollama":
        provider_json.append(
            f'{{"name":"ollama","base_url":"{cfg["base_url"]}","api_key_ref":"",'
            f'"models":["{cfg["model"]}","{cfg["embed_model"]}"],'
            f'"cost_per_1k_input":0,"cost_per_1k_output":0,"max_tokens":8192,'
            f'"supports_streaming":false,"supports_tools":true,"supports_structured_output":false}}'
        )
    elif cfg["provider"] == "gemini":
        provider_json.append(
            f'{{"name":"gemini","base_url":"","api_key_ref":"GEMINI_API_KEY",'
            f'"models":["{cfg["model"]}"],'
            f'"cost_per_1k_input":0,"cost_per_1k_output":0,"max_tokens":8192,'
            f'"supports_streaming":true,"supports_tools":true,"supports_structured_output":true}}'
        )
    elif cfg["provider"] == "openrouter":
        provider_json.append(
            f'{{"name":"openrouter","base_url":"{cfg["base_url"]}","api_key_ref":"OPENROUTER_API_KEY",'
            f'"models":["{cfg["model"]}"],'
            f'"cost_per_1k_input":0,"cost_per_1k_output":0,"max_tokens":8192,'
            f'"supports_streaming":true,"supports_tools":true,"supports_structured_output":true}}'
        )

    lines = [
        "# Nexus Agent — Environment Configuration",
        f"# Generated by setup.py at {cfg['provider']}",
        "",
        "# Database",
        'NEXUS_DATABASE__URL=postgresql+asyncpg://nexus:nexus@localhost:5433/nexus',
        "NEXUS_DATABASE__POOL_SIZE=10",
        "NEXUS_DATABASE__MAX_OVERFLOW=20",
        "",
        "# Redis",
        "NEXUS_REDIS__URL=redis://localhost:6379/0",
        "NEXUS_REDIS__DB=0",
        "",
        "# LLM",
        f'NEXUS_LLM__DEFAULT_PROVIDER={cfg["provider"]}',
        f'NEXUS_LLM__DEFAULT_MODEL={cfg["model"]}',
        "NEXUS_LLM__TEMPERATURE=0.3",
        "NEXUS_LLM__MAX_TOKENS=8192",
        "NEXUS_LLM__TIMEOUT_S=60",
        f'NEXUS_LLM__EMBEDDING_MODEL={cfg["embed_model"]}',
        f'NEXUS_LLM__PROVIDERS=[{",".join(provider_json)}]',
        "",
    ]

    if cfg["api_key"]:
        if cfg["provider"] == "gemini":
            lines.append(f'GEMINI_API_KEY={cfg["api_key"]}')
        elif cfg["provider"] == "openrouter":
            lines.append(f'OPENROUTER_API_KEY={cfg["api_key"]}')
        elif cfg["provider"] == "openai":
            lines.append(f'OPENAI_API_KEY={cfg["api_key"]}')
        lines.append("")

    lines.extend([
        "# Auth",
        "NEXUS_AUTH__JWT_SECRET=change-me-to-a-strong-random-secret",
        "NEXUS_AUTH__JWT_ALGORITHM=HS256",
        "NEXUS_AUTH__ACCESS_TOKEN_TTL_MINUTES=30",
        "",
        "# Agent",
        "NEXUS_AGENT__MAX_ITERATIONS=10",
        "NEXUS_AGENT__MAX_SUB_ITERATIONS=3",
        "NEXUS_AGENT__HITL_DEFAULT=false",
        "NEXUS_AGENT__SKIP_PREVIEW=true",
        "",
        "# Tools",
        "NEXUS_TOOLS__EXECUTION_TIMEOUT_S=30",
        "NEXUS_TOOLS__SANDBOX_ENABLED=false",
        'NEXUS_TOOLS__ALLOWED_HOSTS=["*"]',
        "",
        "# Server",
        "NEXUS_SERVER__HOST=0.0.0.0",
        "NEXUS_SERVER__PORT=8000",
        'NEXUS_SERVER__CORS_ORIGINS=["*"]',
        "NEXUS_SERVER__DOCS_URL=/docs",
        "",
    ])

    ENV_FILE.write_text("\n".join(lines))
    print(f"  ✅ Created {ENV_FILE}")


def run_migrations() -> None:
    print("\n🗄️  Running database migrations...")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("  ✅ Migrations applied")
    else:
        print(f"  ⚠️  Migrations failed: {result.stderr[:200]}")
        print("  Run manually: uv run alembic upgrade head")


def seed_demo_data() -> None:
    print("\n🌱 Seeding demo data...")
    result = subprocess.run(
        [sys.executable, "-m", "scripts.seed", "--no-embed"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("  ✅ Demo data seeded")
    else:
        print(f"  ⚠️  Seeding failed: {result.stderr[:200]}")
        print("  Run manually: uv run python scripts/seed.py")


def start_dev_servers() -> None:
    print("\n🚀 Starting dev servers...")
    print("  Backend:  uv run uvicorn nexus.main:create_app --factory --reload --port 8000")
    print("  Frontend: cd frontend && npm run dev")
    print("\n  Or use Docker: docker compose up")


def main() -> None:
    parser = argparse.ArgumentParser(description="Nexus Agent setup wizard")
    parser.add_argument("--auto", action="store_true", help="Non-interactive mode")
    args = parser.parse_args()

    print("╔══════════════════════════════════════════╗")
    print("║     Nexus Agent — Setup Wizard           ║")
    print("╚══════════════════════════════════════════╝")

    if not check_prerequisites():
        print("\n❌ Fix the issues above and re-run.")
        sys.exit(1)

    if args.auto:
        cfg = {
            "provider": "ollama",
            "model": "ollama/qwen2.5:7b",
            "embed_model": "ollama/nomic-embed-text",
            "api_key": "",
            "base_url": "http://localhost:11434",
        }
    else:
        cfg = pick_llm_provider()

    generate_env(cfg)
    run_migrations()
    seed_demo_data()

    print("\n" + "=" * 50)
    print("✅ Setup complete!")
    start_dev_servers()
    print("\n📖 Documentation: docs/quickstart.md")
    print("=" * 50)


if __name__ == "__main__":
    main()
