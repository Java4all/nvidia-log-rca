# Log-RCA — draft (presentation)

> Minimal text; diagrams carry the story.

## 1. System context

```mermaid
flowchart LR
  U[User / QA] --> B[Browser]
  B --> N[nginx :80]
  N --> UI[Chainlit UI]
  N --> API[FastAPI]
  UI -->|HTTP JSON/SSE| API
  API --> O[Ollama LLM + embed]
  API --> HF[HuggingFace cache\nreranker model]
```

## 2. Containers (Docker)

```mermaid
flowchart TB
  subgraph Host
    NG[nginx]
    UI[ui : Chainlit]
    AP[api : FastAPI + bat_ai]
    OL[ollama : GPU]
    VOL[(models volume)]
    HFV[(hf_cache volume)]
  end
  NG --> UI
  NG --> AP
  UI --> AP
  AP --> OL
  OL --- VOL
  AP --- HFV
```

## 3. Components — role

| Piece | Role |
|-------|------|
| **nginx** | Reverse proxy; `/` → UI, `/api` → API |
| **Chainlit UI** | Upload log, chat, SSE progress |
| **FastAPI** | Streams LangGraph pipeline events |
| **bat_ai** | Compiled **LangGraph** state machine |
| **Ollama** | LLM inference + embedding models |
| **HybridRetriever** | BM25 + FAISS over log chunks |
| **FlagReranker** | Cross-encoder rerank (HF) |

```mermaid
flowchart LR
  UI[Chainlit UI] --> API[FastAPI]
  API --> LG[LangGraph bat_ai]
  LG --> RT[HybridRetriever\nBM25 + FAISS]
  LG --> OL[Ollama LLM]
  RT --> OL
```

## 4. LangGraph pipeline (RAG + self-correction)

```mermaid
flowchart TD
  START([start]) --> R[retrieve]
  R --> RR[rerank]
  RR --> G[grade_documents]
  G --> D{relevant\nchunks?}
  D -->|no / empty| TQ[transform_query]
  TQ --> R
  D -->|yes| GEN[generate]
  GEN --> V{answer\nok?}
  V -->|not useful| TQ
  V -->|useful| END([end])
  V -->|hallucination guard| GEN
```

## 5. End-to-end (happy path)

```mermaid
sequenceDiagram
  participant U as User
  participant UI as Chainlit
  participant API as FastAPI
  participant G as LangGraph
  participant O as Ollama

  U->>UI: upload log + question
  UI->>API: POST /api/analyze/stream
  API->>G: stream graph
  G->>O: embed + retrieve
  G->>O: LLM grade / rewrite / generate
  API-->>UI: SSE steps + result
  UI-->>U: RCA + evidence
```

## 6. Retrieve internals

```mermaid
flowchart LR
  LOG[(log file)] --> SPLIT[chunk\n20k/10k overlap]
  SPLIT --> BM25[BM25 retriever]
  SPLIT --> EMB[OllamaEmbeddings]
  EMB --> FAISS[FAISS similarity\nthreshold 0.8]
  BM25 --> ENS[Ensemble 0.5/0.5]
  FAISS --> ENS
```
