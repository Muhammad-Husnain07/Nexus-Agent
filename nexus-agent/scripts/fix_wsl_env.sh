#!/usr/bin/env bash
# Fix WSL2 .env for Ollama (built-in LiteLLM provider)
ENV="$HOME/nexus-agent/.env"
# Remove old OpenAI-specific settings
sed -i '/^OPENAI_API_KEY/d' "$ENV"
sed -i '/^OLLAMA_API_BASE/d' "$ENV"
# Update LLM settings
sed -i 's/^NEXUS_LLM__DEFAULT_PROVIDER=.*/NEXUS_LLM__DEFAULT_PROVIDER=ollama/' "$ENV"
sed -i 's|^NEXUS_LLM__DEFAULT_MODEL=.*|NEXUS_LLM__DEFAULT_MODEL=ollama/qwen2.5:7b|' "$ENV"
sed -i 's|^NEXUS_LLM__EMBEDDING_MODEL=.*|NEXUS_LLM__EMBEDDING_MODEL=ollama/nomic-embed-text|' "$ENV"
sed -i 's/^NEXUS_LLM__PROVIDERS=.*/NEXUS_LLM__PROVIDERS=[]/' "$ENV"
echo FIXED
