#!/bin/bash
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/bin:/usr/local/bin"
export NEXUS_DATABASE__URL="postgresql+asyncpg://nexus:nexus@172.27.160.1:5433/nexus"
export NEXUS_REDIS__URL="redis://172.27.160.1:6379/0"
export NEXUS_LLM__DEFAULT_PROVIDER="ollama"
export NEXUS_LLM__DEFAULT_MODEL="ollama/qwen2.5:7b"
export NEXUS_LLM__TEMPERATURE="0.3"
export NEXUS_LLM__MAX_TOKENS="8192"
export NEXUS_LLM__TIMEOUT_S="300"
export NEXUS_LLM__MAX_RETRIES="3"
export NEXUS_LLM__EMBEDDING_MODEL="ollama/nomic-embed-text"
export NEXUS_LLM__EMBEDDING_DIMENSIONS="768"
export NEXUS_LLM__PROVIDERS='[{"name":"ollama","base_url":"http://172.27.160.1:11434","api_key_ref":"","models":["ollama/qwen2.5:7b","ollama/nomic-embed-text"],"cost_per_1k_input":0,"cost_per_1k_output":0,"max_tokens":8192,"supports_streaming":true,"supports_tools":true,"supports_structured_output":false}]'
export NEXUS_SERVER__HOST="0.0.0.0"
export NEXUS_SERVER__PORT="8000"
export NEXUS_SERVER__CORS_ORIGINS='["*"]'
export NEXUS_TOOLS__EXECUTION_TIMEOUT_S="30"
export NEXUS_TOOLS__MAX_RETRIES="3"
export NEXUS_TOOLS__SANDBOX_ENABLED="true"
export NEXUS_TOOLS__ALLOWED_HOSTS='["*"]'
export NEXUS_OBSERVABILITY__LOG_LEVEL="INFO"
export NEXUS_OBSERVABILITY__LOG_FORMAT="console"
export NEXUS_AGENT__MAX_ITERATIONS="25"
export NEXUS_AGENT__HITL_DEFAULT="false"

cd ~/nexus-agent
source .venv/bin/activate
nohup uv run uvicorn nexus.main:app --host 0.0.0.0 --port 8000 --workers 1 --log-level error > ~/nexus-server.log 2>&1 &
echo "Nexus PID: $!"
echo "Started. Check log: tail -f ~/nexus-server.log"
