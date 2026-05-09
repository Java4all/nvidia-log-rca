# 🔍 Jenkins RCA — BAT.AI

**The real NVIDIA BAT.AI (Bug Automation Tool) pipeline running locally on Ollama.**

This project takes the exact source files from
`community/log_analysis_multi_agent_rag` (NVIDIA GenerativeAIExamples)
and runs them on EC2 g6.xlarge with local Ollama models instead of NVIDIA NIM APIs.

## What changed vs the NVIDIA original

| File | Change |
|---|---|
| `utils.py` | `ChatNVIDIA` → `ChatOllama` |
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

## Usage

1. Open `http://<ec2-ip>`
2. Upload a Jenkins log file
3. Ask: *"What caused the build failure?"*

## Hardware: EC2 g6.xlarge
- NVIDIA L4 GPU · 24 GB VRAM
- Recommended model: `qwen2.5:14b-instruct-q4_K_M` (~9 GB)
