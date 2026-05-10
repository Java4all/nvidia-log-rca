# syntax=docker/dockerfile:1
# Layer order: base OS deps → pip deps (cached via BuildKit) → application source last.
# Rebuilds skip pip when only agents/api change if requirements.txt is unchanged.
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Persist pip downloads/wheels between builds (needs DOCKER_BUILDKIT=1)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY agents/ ./agents/
COPY api/    ./api/

ENV PYTHONPATH=/app

HEALTHCHECK --interval=15s --timeout=10s --start-period=30s --retries=5 \
    CMD curl -sf http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
