#!/bin/sh
set -e
OLLAMA_HOST="${OLLAMA_HOST:-http://ollama:11434}"
LLM_MODEL="${LLM_MODEL:-mistral:7b-instruct-q4_K_M}"
EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"

echo "[init] Waiting for Ollama..."
until curl -sf "${OLLAMA_HOST}/api/tags" > /dev/null 2>&1; do
    echo "[init] Not ready, retrying in 5s..."
    sleep 5
done
echo "[init] Ollama is up."

pull_model() {
    MODEL="$1"
    TAGS=$(curl -sf "${OLLAMA_HOST}/api/tags")
    if echo "${TAGS}" | grep -q "\"name\":\"${MODEL}\""; then
        echo "[init] ${MODEL} already present."
    else
        echo "[init] Pulling ${MODEL}..."
        curl -sf -X POST "${OLLAMA_HOST}/api/pull" \
            -H "Content-Type: application/json" \
            -d "{\"name\":\"${MODEL}\"}" | grep -o '"status":"[^"]*"' | tail -1
        echo "[init] Done: ${MODEL}"
    fi
}

pull_model "${LLM_MODEL}"
pull_model "${EMBED_MODEL}"
echo "[init] All models ready."
