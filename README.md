# Log-RCA

**Root cause analysis for build logs** — NVIDIA BAT.AI–style multi-agent RAG (`community/log_analysis_multi_agent_rag`), packaged with **FastAPI**, **Chainlit**, **Ollama** (LLM + embeddings), and optional **NVIDIA AI Endpoints** for the chat model.

---

## Features

| Area | What you get |
|------|----------------|
| **UI (Chainlit)** | Log upload (first screen + **Replace log**), live **pipeline checklist** (retrieve → rank → grade → refine → analyze), **quick-question** buttons, structured RCA, **supporting evidence** (Markdown excerpts), **Export last report** (download + optional copy block) |
| **API** | `POST /api/analyze`, `POST /api/analyze/stream` (SSE for the UI), `GET /api/health` (includes `llm_backend`, `llm_model`, embed model, Ollama status) |
| **LLM** | **Default:** `ChatOllama` via `LLM_MODEL`. **Optional:** `ChatNVIDIA` with `LLM_BACKEND=nvidia` + `NVIDIA_API_KEY` + optional `NVIDIA_LLM_MODEL` |
| **Retrieval** | Same hybrid design as upstream: **BM25 + FAISS** over **Ollama embeddings** (`EMBED_MODEL`), local **cross-encoder rerank** (`RERANKER_MODEL`) |
| **Ops** | **Docker Compose** (Ollama GPU, API, UI, **nginx** on port **80**), **Makefile** with cached / no-cache builds |

Detail install for EC2, GPU checks, and ports: **[docs/INSTALLATION.md](docs/INSTALLATION.md)**.

---

## Quick start

```bash
make setup    # copy .env.example → .env (if missing)
make build    # build images (Docker BuildKit layer cache)
make up       # start stack + pull Ollama models (follow logs; Ctrl+C leaves stack running)
```

Then open **http://localhost** (or `http://<host-ip>`). API docs: **http://localhost/docs**, health: **http://localhost/api/health**.

Useful targets: **`make build-nocache`** (clean rebuild), **`make build-ui`** / **`make build-ui-nocache`** (UI only + `up -d ui`), **`make logs-api`**, **`make health`**, **`make down`**.

---

## Configuration (`.env`)

Copy **[.env.example](.env.example)** to `.env` and adjust.

| Variable | Role |
|----------|------|
| `LLM_BACKEND` | `ollama` (default) or `nvidia` |
| `LLM_MODEL` | Ollama chat model when `LLM_BACKEND=ollama` |
| `NVIDIA_API_KEY` | Required if `LLM_BACKEND=nvidia` |
| `NVIDIA_LLM_MODEL` | Optional; defaults to upstream-style Nemotron id if unset |
| `EMBED_MODEL` | Ollama embedding model (FAISS) |
| `RERANKER_MODEL` | Hugging Face cross-encoder for reranking |
| `MAX_LOG_BYTES` | API upload limit (bytes) |
| `MAX_LOG_MB` | UI upload cap (Chainlit; compose passes through) |
| `EVIDENCE_MAX_CHUNKS` | Max evidence excerpts shown in the UI (default `8`) |
| `EVIDENCE_PREVIEW_CHARS` | Max characters per excerpt (default `1500`) |

---

## NVIDIA API key (cloud LLM)

1. Open the **[NVIDIA API Catalog](https://build.nvidia.com/)**, sign in, pick a model, and use **Get API Key** → **Generate Key** (see also [NIM — generate an API key](https://docs.nvidia.com/nim/large-language-models/latest/getting-started.html#generate-an-api-key)).
2. Set **`NVIDIA_API_KEY`**, **`LLM_BACKEND=nvidia`**, and optionally **`NVIDIA_LLM_MODEL`**, then recreate containers so the API picks up env (`docker compose up -d` or `make up`).
3. Embeddings still use **Ollama** unless you change **`multiagent.py`**.

If you see **`403` / Authorization failed** during analysis, the key is invalid, not entitled for that model, or the wrong key type (use the **Catalog** API key for `ChatNVIDIA`, not an unrelated legacy key).

---

## UI behavior (summary)

- **Structured answer:** prompts ask the model for Markdown sections **Summary**, **Key issues**, **Error details**, **Recommendations** (see `app/agents/prompt.json`).
- **Replace log** clears the cached export and loads a new file without refreshing the page.
- **Export last report** appears after a successful run; large reports may be download-only (copy block is skipped over ~28k chars).

---

## What changed vs the NVIDIA original

| Piece | Change |
|-------|--------|
| `app/agents/utils.py` | Default **`ChatOllama`**; optional **`ChatNVIDIA`** |
| `app/agents/multiagent.py` | `NVIDIAEmbeddings` → **`OllamaEmbeddings`** |
| `app/agents/graphnodes.py` | `NVIDIARerank` → **`FlagReranker`** (configurable model) |
| `app/agents/binary_score_models.py` | Pydantic v2–compatible |
| `app/agents/prompt.json` | **Tuned** for fixed RCA Markdown headings + clearer QA instructions |
| `bat_ai.py`, `graphedges.py`, `example.py` | Same graph / edges as upstream |

**Added in this repo:** `app/api/main.py` (FastAPI), `app/ui/` (Chainlit + branding), `nginx/`, `docker-compose.yml`, `Makefile`, `chainlit.md`, UI assets under `app/ui/public/`.

---

## Hardware (reference): EC2 g6.xlarge

- NVIDIA L4 · ~24 GB VRAM  
- Example chat model: `qwen2.5:14b-instruct-q4_K_M` (~9 GB) — set **`LLM_MODEL`** in `.env` and run **`make pull-models`** after changes.

---

## More docs

- **[docs/INSTALLATION.md](docs/INSTALLATION.md)** — EC2, Docker GPU, ports, troubleshooting  
- **[docs/presentation/README.md](docs/presentation/README.md)** — draft architecture narrative (Markdown / HTML / PDF)
