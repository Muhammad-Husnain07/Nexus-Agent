#!/usr/bin/env bash
# Point WSL2 to Windows Ollama via host.docker.internal
# Also set OLLAMA_HOST so LiteLLM can find it
ENV="$HOME/nexus-agent/.env"
echo "" >> "$ENV"
echo "# Ollama runs on Windows host - access via host.docker.internal" >> "$ENV"
echo "OLLAMA_HOST=http://host.docker.internal:11434" >> "$ENV"
echo "FIXED"
