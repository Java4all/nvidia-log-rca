# Log-RCA

**Root cause analysis for build logs — NVIDIA BAT.AI–based pipeline running locally on Ollama.**

This project takes the exact source files from
`community/log_analysis_multi_agent_rag` (NVIDIA GenerativeAIExamples)
and runs them on EC2 g6.xlarge with local Ollama models instead of NVIDIA NIM APIs.

## What changed vs the NVIDIA original

| File | Change |
|---|---|
| `utils.py` | Default **`ChatOllama`**; optional **`ChatNVIDIA`** (`LLM_BACKEND=nvidia`, `NVIDIA_API_KEY`) |
| `multiagent.py` | `NVIDIAEmbeddings` → `OllamaEmbeddings` |
| `graphnodes.py` | `NVIDIARerank` → `FlagReranker` (BAAI/bge-reranker-v2-m3) |
| `binary_score_models.py` | `pydantic_v1` → `pydantic` (v2 compat) |
| `bat_ai.py`, `graphedges.py`, `example.py`, `prompt.json` | **Unchanged** |

## Quick start

```bash
make setup    # create .env
make build    # build images (~5 min)
make up       # start + pull models
# open http://<ec2-ip>
```

### NVIDIA API key (for `ChatNVIDIA` / cloud LLM)

1. Use an NVIDIA account and follow **[NIM — generate an API key](https://docs.nvidia.com/nim/large-language-models/latest/getting-started.html#generate-an-api-key)** (NGC / NVIDIA Build, depending on your flow).
2. Put the key in `.env` as **`NVIDIA_API_KEY=...`**, set **`LLM_BACKEND=nvidia`**, and optionally **`NVIDIA_LLM_MODEL`** (default matches [upstream BAT.AI](https://github.com/NVIDIA/GenerativeAIExamples/tree/main/community/log_analysis_multi_agent_rag): `nvidia/llama-3.3-nemotron-super-49b-v1.5`).
3. Rebuild the API image after dependency changes: `make build` (embeddings still use **Ollama** unless you change `multiagent.py`).

## Usage

1. Open `http://<ec2-ip>`
2. Upload a Jenkins log file
3. Ask: *"What caused the build failure?"*

## Hardware: EC2 g6.xlarge
- NVIDIA L4 GPU · 24 GB VRAM
- Recommended model: `qwen2.5:14b-instruct-q4_K_M` (~9 GB)
