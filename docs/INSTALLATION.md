# Installation Guide

## What this is

The **real** NVIDIA BAT.AI pipeline (`community/log_analysis_multi_agent_rag`)
running locally on EC2 g6.xlarge using Ollama instead of NVIDIA NIM APIs.

### Files from NVIDIA (unchanged)
- `bat_ai.py` — LangGraph graph definition
- `graphedges.py` — `decide_to_generate`, `grade_generation_vs_documents_and_question`
- `example.py` — original CLI entry point
- `prompt.json` — all 6 prompt templates (verbatim)

### Files adapted for local (minimal changes)
- `utils.py` — `ChatNVIDIA` → `ChatOllama`
- `multiagent.py` — `NVIDIAEmbeddings` → `OllamaEmbeddings`, same chunk sizes (20000/10000), same EnsembleRetriever weights (0.5/0.5)
- `graphnodes.py` — `NVIDIARerank` → `FlagReranker(BAAI/bge-reranker-v2-m3)`
- `binary_score_models.py` — `pydantic_v1` → `pydantic` (v2 compatibility fix)

### Added
- `api/main.py` — FastAPI wrapper around `bat_ai.app.stream()`
- `ui/app.py` — Chainlit chat UI
- Docker Compose + Makefile + Nginx

---

## Prerequisites

- EC2 **g6.xlarge** (NVIDIA L4 · 24 GB VRAM)
- AMI: **Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04)**
- EBS: ≥ 50 GB
- Security group: inbound TCP 80, 22
- Docker + Docker Compose + NVIDIA Container Toolkit

Verify GPU in Docker:
```bash
docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi
```

---

## Quick Start

```bash
git clone https://github.com/your-org/jenkins-rca.git
cd jenkins-rca

make setup    # creates .env — pick your model
make build    # builds api + ui images
make up       # starts everything, pulls Ollama models
```

Open `http://<EC2-PUBLIC-IP>` in your browser.

---

## Model selection (edit `.env`)

| Model | VRAM | Notes |
|---|---|---|
| `mistral:7b-instruct-q4_K_M` | ~4 GB | Fastest, default |
| `llama3.1:8b-instruct-q4_K_M` | ~5 GB | Best general |
| `qwen2.5:14b-instruct-q4_K_M` | ~9 GB | **Best for logs** ← recommended |

After changing model:
```bash
make pull-models
make restart-api
```

---

## Makefile reference

```
make setup          Create .env
make build          Build images
make up             Start + pull models
make down           Stop (keep data)
make destroy        Stop + delete all data ⚠️

make logs           All container logs
make logs-api       API logs
make logs-ui        UI logs
make logs-ollama    Ollama logs
make ps             Container status
make health         API health check

make pull-models    Pull/update models
make restart-api    Restart API
make restart-ui     Restart UI
make shell-api      Shell in API container
make shell-ui       Shell in UI container
make clean          Prune dangling images
```

---

## CLI usage (original NVIDIA style)

You can still use the original `example.py` CLI directly inside the API container:

```bash
make shell-api
cd /app/agents
python example.py /path/to/jenkins.log \
  --question "What caused the build failure?"
```

---

## Troubleshooting

**Ollama not using GPU**
```bash
docker exec rca-ollama nvidia-smi
# Should show Ollama process using the L4
```

**Reranker slow on first run**
The `BAAI/bge-reranker-v2-m3` model (~1.1 GB) downloads from HuggingFace on first use.
It is cached in the `hf_cache` Docker volume for subsequent runs.

**API restarting**
```bash
make logs-api   # usually Ollama not ready yet — wait 60s
```

**Large log files timing out**
- Default limit: 50 MB. Increase `MAX_LOG_BYTES` in `.env`
- Nginx timeout: 600s — increase `proxy_read_timeout` in `nginx/nginx.conf` if needed

---

## Cost (EC2 g6.xlarge, ~$0.80/hr on-demand)

Stop when not in use — EBS volume and model weights persist:
```bash
aws ec2 stop-instances --instance-ids <id>
```
