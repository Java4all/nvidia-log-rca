# syntax=docker/dockerfile:1
# Layer order: OS → pip (heavy, cached) → config/static → app.py last so UI code edits
# only invalidate the final layer.
FROM python:3.11-slim

WORKDIR /ui

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY .chainlit/ .chainlit/
COPY public/ public/
COPY app.py .

ENV PYTHONPATH=/ui

CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8080", "--headless"]
