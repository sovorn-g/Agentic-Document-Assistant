#!/usr/bin/env bash
set -euo pipefail

cd /app

if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

LLM_PROVIDER="${LLM_PROVIDER:-ollama}"
LLM_MODEL="${LLM_MODEL:-qwen3:4b-instruct-2507-q4_K_M}"

case "$LLM_PROVIDER" in
  ollama)
    if ! command -v ollama >/dev/null 2>&1; then
      echo "Ollama is not installed in this image." >&2
      echo "Rebuild the Docker image with INSTALL_OLLAMA=1 before using LLM_PROVIDER=ollama." >&2
      exit 1
    fi
    echo "Starting Ollama for local model: $LLM_MODEL"
    ollama serve &
    echo "Waiting for Ollama..."
    until curl -fsS http://localhost:11434 >/dev/null 2>&1; do
      sleep 1
    done
    echo "Ensuring Ollama model is available: $LLM_MODEL"
    ollama pull "$LLM_MODEL" || true
    ;;
  openai|google|deepseek)
    echo "Using hosted LLM provider: $LLM_PROVIDER"
    ;;
  *)
    echo "Unsupported LLM_PROVIDER=$LLM_PROVIDER" >&2
    echo "Supported providers: ollama, openai, google, deepseek" >&2
    exit 1
    ;;
esac

exec python app.py
