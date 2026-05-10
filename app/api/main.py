"""
FastAPI backend for Log-RCA

Endpoints:
  POST /api/analyze          – full RCA, returns JSON when complete
  POST /api/analyze/stream   – SSE stream: yields agent steps live, then final result
  GET  /api/health           – health check
  GET  /api/models           – list Ollama models
"""
import os
import sys
import json
import tempfile
import httpx

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List

sys.path.insert(0, "/app/agents")
import bat_ai

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
MAX_LOG_BYTES   = int(os.getenv("MAX_LOG_BYTES", str(50 * 1024 * 1024)))


def _format_stream_error(exc: Exception) -> str:
    """Surface actionable hints when NVIDIA cloud LLM rejects the request."""
    msg = str(exc)
    backend = os.getenv("LLM_BACKEND", "ollama").lower().strip()
    if backend != "nvidia":
        return msg
    low = msg.lower()
    if "403" in msg or "authorization failed" in low or "401" in msg:
        return (
            f"{msg} "
            "— NVIDIA AI Endpoints rejected this call. Verify NVIDIA_API_KEY (NGC), "
            "that your account can use NVIDIA_LLM_MODEL, or set LLM_BACKEND=ollama "
            "with Ollama running."
        )
    return msg

# Human-readable labels for each graph node — for QA engineers
NODE_LABELS = {
    "retrieve":        ("🔍", "Retrieving log chunks",    "Hybrid BM25 + FAISS search across log file"),
    "rerank":          ("📊", "Reranking results",         "Scoring chunks by relevance to your question"),
    "grade_documents": ("✅", "Grading documents",         "Filtering out irrelevant chunks"),
    "generate":        ("🤖", "Generating RCA",            "LLM analysing evidence and writing root cause"),
    "transform_query": ("🔄", "Refining query",            "Self-correcting — rewriting question for better retrieval"),
}

app = FastAPI(title="Log-RCA API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Models ────────────────────────────────────────────────────────────────────

class DocumentChunk(BaseModel):
    content:  str
    metadata: dict

class AnalyzeResponse(BaseModel):
    answer:    str
    question:  str
    documents: List[DocumentChunk]

class HealthResponse(BaseModel):
    status:       str
    ollama:       str
    llm_backend:  str
    llm_model:    str
    embed_model:  str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_temp(raw: bytes) -> str:
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".log", delete=False) as f:
        f.write(raw)
        return f.name


def _stream_pipeline(question: str, tmp_path: str):
    """
    Blocking generator — runs bat_ai.app.stream() and yields SSE strings.

    Event types (JSON in data field):
      step   – {type, node, icon, label, detail}
      result – {type, answer, question, documents}
      error  – {type, message}
    """
    inputs = {"question": question, "path": tmp_path}
    value  = {}
    try:
        for output in bat_ai.app.stream(inputs):
            for node_name, node_value in output.items():
                value = node_value
                icon, label, detail = NODE_LABELS.get(
                    node_name, ("⚙️", node_name, "")
                )
                yield f"data: {json.dumps({'type':'step','node':node_name,'icon':icon,'label':label,'detail':detail})}\n\n"

        docs   = value.get("documents", [])
        result = {
            "type":      "result",
            "answer":    value.get("generation", ""),
            "question":  value.get("question", question),
            "documents": [
                {"content": d.page_content, "metadata": d.metadata}
                for d in docs
            ],
        }
        yield f"data: {json.dumps(result)}\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'type':'error','message':_format_stream_error(e)})}\n\n"
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/health", response_model=HealthResponse)
async def health():
    embed_model = os.getenv("EMBED_MODEL", "nomic-embed-text")
    backend     = os.getenv("LLM_BACKEND", "ollama").lower().strip()
    if backend == "nvidia":
        llm_model = (
            os.getenv("NVIDIA_LLM_MODEL", "").strip()
            or "nvidia/llama-3.3-nemotron-super-49b-v1.5"
        )
    else:
        llm_model = os.getenv("LLM_MODEL", "mistral:7b-instruct-q4_K_M")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r  = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            ok = "ok" if r.status_code == 200 else "degraded"
    except Exception:
        ok = "unreachable"
    return HealthResponse(
        status="ok",
        ollama=ok,
        llm_backend=backend,
        llm_model=llm_model,
        embed_model=embed_model,
    )


@app.get("/api/models")
async def list_models():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            r.raise_for_status()
            return {"models": [m["name"] for m in r.json().get("models", [])]}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Ollama unreachable: {e}")


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(
    log_file: UploadFile = File(...),
    question: str        = Form(...),
):
    """Blocking — returns full result as JSON."""
    raw = await log_file.read()
    if len(raw) > MAX_LOG_BYTES:
        raise HTTPException(status_code=413,
            detail=f"File exceeds {MAX_LOG_BYTES // 1024 // 1024} MB limit.")
    if not raw.strip():
        raise HTTPException(status_code=400, detail="Log file is empty.")

    tmp_path = _write_temp(raw)
    value    = {}
    try:
        for output in bat_ai.app.stream({"question": question, "path": tmp_path}):
            for _, v in output.items():
                value = v
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Pipeline error: {_format_stream_error(e)}"
        )
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    docs = value.get("documents", [])
    return AnalyzeResponse(
        answer=value.get("generation", ""),
        question=value.get("question", question),
        documents=[DocumentChunk(content=d.page_content, metadata=d.metadata)
                   for d in docs],
    )


@app.post("/api/analyze/stream")
async def analyze_stream(
    log_file: UploadFile = File(...),
    question: str        = Form(...),
):
    """
    SSE streaming endpoint — yields agent step events live, then the final result.
    Used by Chainlit UI to show pipeline progress in real time.
    """
    raw = await log_file.read()
    if len(raw) > MAX_LOG_BYTES:
        raise HTTPException(status_code=413,
            detail=f"File exceeds {MAX_LOG_BYTES // 1024 // 1024} MB limit.")
    if not raw.strip():
        raise HTTPException(status_code=400, detail="Log file is empty.")

    tmp_path = _write_temp(raw)
    # Pass a sync generator — Starlette wraps it with iterate_in_threadpool(), which
    # safely converts StopIteration (see starlette.concurrency._next). Do not use
    # asyncio.run_in_executor(next, gen): that leaks StopIteration into futures.
    return StreamingResponse(
        _stream_pipeline(question, tmp_path),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",   # disable Nginx buffering for SSE
        },
    )
