"""
FastAPI backend for Jenkins RCA — BAT.AI
Wraps the real NVIDIA bat_ai.app.stream() exactly as example.py does.

Endpoints:
  POST /api/analyze   – run full RCA pipeline on uploaded log + question
  GET  /api/health    – health check
  GET  /api/models    – list Ollama models
"""
import os
import sys
import tempfile
import httpx

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

# Add agents dir to path so bat_ai imports work
sys.path.insert(0, "/app/agents")
import bat_ai  # imports the compiled app

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
MAX_LOG_BYTES   = int(os.getenv("MAX_LOG_BYTES", str(50 * 1024 * 1024)))

app = FastAPI(
    title="Jenkins RCA — BAT.AI API",
    description="Self-corrective multi-agent RAG for Jenkins log RCA. "
                "Runs the real NVIDIA BAT.AI pipeline locally via Ollama.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class DocumentChunk(BaseModel):
    content:  str
    metadata: dict


class AnalyzeResponse(BaseModel):
    answer:    str
    question:  str
    documents: List[DocumentChunk]


class HealthResponse(BaseModel):
    status:      str
    ollama:      str
    llm_model:   str
    embed_model: str


@app.get("/api/health", response_model=HealthResponse)
async def health():
    llm_model   = os.getenv("LLM_MODEL",   "mistral:7b-instruct-q4_K_M")
    embed_model = os.getenv("EMBED_MODEL",  "nomic-embed-text")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r  = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            ok = "ok" if r.status_code == 200 else "degraded"
    except Exception:
        ok = "unreachable"
    return HealthResponse(status="ok", ollama=ok,
                          llm_model=llm_model, embed_model=embed_model)


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
    raw = await log_file.read()
    if len(raw) > MAX_LOG_BYTES:
        raise HTTPException(status_code=413,
            detail=f"File exceeds {MAX_LOG_BYTES // 1024 // 1024} MB limit.")
    if not raw.strip():
        raise HTTPException(status_code=400, detail="Log file is empty.")

    # Write to temp file — TextLoader needs a real file path (as in original)
    with tempfile.NamedTemporaryFile(
        mode="wb", suffix=".log", delete=False
    ) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name

    try:
        # Mirror example.py exactly: stream inputs through bat_ai.app
        inputs = {"question": question, "path": tmp_path}
        value  = {}
        try:
            for output in bat_ai.app.stream(inputs):
                for key, value in output.items():
                    print(f"Node: {key}")
        except Exception as e:
            raise HTTPException(status_code=500,
                                detail=f"Pipeline error: {e}")

        generation = value.get("generation", "")
        documents  = value.get("documents", [])
        final_q    = value.get("question", question)

        return AnalyzeResponse(
            answer=generation,
            question=final_q,
            documents=[
                DocumentChunk(
                    content=d.page_content,
                    metadata=d.metadata,
                )
                for d in documents
            ],
        )
    finally:
        os.unlink(tmp_path)
