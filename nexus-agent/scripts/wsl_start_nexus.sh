#!/bin/bash
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/bin:/usr/local/bin"
cd ~/nexus-agent || exit 1
source .venv/bin/activate

# Find Windows host IP
GW=$(ip route show default 2>/dev/null | awk '{print $3}')
echo "Gateway: $GW"
echo "Testing Ollama via gateway..."
curl -s --max-time 5 http://$GW:11434/api/tags 2>&1 | head -2
echo "Testing Ollama via localhost..."
curl -s --max-time 5 http://localhost:11434/api/tags 2>&1 | head -2

# Write .env with correct Ollama URL
cat > .env << ENVEOF
NEXUS_DATABASE__URL=postgresql+asyncpg://nexus:nexus@$GW:5433/nexus
NEXUS_REDIS__URL=redis://$GW:6379/0
NEXUS_LLM__DEFAULT_PROVIDER=ollama
NEXUS_LLM__DEFAULT_MODEL=ollama/qwen2.5:7b
NEXUS_LLM__TEMPERATURE=0.3
NEXUS_LLM__MAX_TOKENS=8192
NEXUS_LLM__TIMEOUT_S=300
NEXUS_LLM__MAX_RETRIES=3
NEXUS_LLM__EMBEDDING_MODEL=ollama/nomic-embed-text
NEXUS_LLM__EMBEDDING_DIMENSIONS=768
NEXUS_LLM__PROVIDERS=[{"name":"ollama","base_url":"http://$GW:11434","api_key_ref":"","models":["ollama/qwen2.5:7b","ollama/nomic-embed-text"],"cost_per_1k_input":0,"cost_per_1k_output":0,"max_tokens":8192,"supports_streaming":true,"supports_tools":true,"supports_structured_output":false}]
NEXUS_SERVER__HOST=0.0.0.0
NEXUS_SERVER__PORT=8000
NEXUS_SERVER__CORS_ORIGINS=["*"]
NEXUS_TOOLS__EXECUTION_TIMEOUT_S=30
NEXUS_TOOLS__MAX_RETRIES=3
NEXUS_TOOLS__SANDBOX_ENABLED=true
NEXUS_TOOLS__ALLOWED_HOSTS=["*"]
NEXUS_OBSERVABILITY__LOG_LEVEL=INFO
NEXUS_OBSERVABILITY__LOG_FORMAT=console
NEXUS_AGENT__MAX_ITERATIONS=25
NEXUS_AGENT__HITL_DEFAULT=false
ENVEOF

echo "Starting Nexus on port 8000..."
uv run uvicorn nexus.main:app --host 0.0.0.0 --port 8000 --workers 1 --log-level error
