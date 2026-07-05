# Architecture

## Pipeline

```
data/source/  ──►  preparers/  ──►  data/prepared/  ──►  ingestion  ──►  Qdrant
   (raw)          (host, uv)        (clean .md)         (docker)         (search index)
```

1. **Source** — raw documentation in framework-specific formats (Jekyll, MDX, Python)
2. **Preparers** — per-framework transformers that clean and normalize to standard Markdown. Runs on host via `uv`.
3. **Prepared** — clean `.md` files in `data/prepared/{framework}/`. Atomic publish via staging + rename.
4. **Ingestion** — runs in Docker container: chunks, embeds (fastembed ONNX), builds TF-IDF sparse vectors, upserts to Qdrant.
5. **Search** — server queries Qdrant (dense + sparse vectors), fuses with server-side RRF, deduplicates by parent section.

## Component Interaction

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  fastembed   │◄────│   Embedder   │────►│    Qdrant    │
│  (in-process)│     │  (in docker) │     │  (embedded)  │
│   (ONNX)     │     │              │     │              │
└──────────────┘     └──────────────┘     └──────────────┘
                                 │                    │
                                 ▼                    ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  TF-IDF      │◄────│   Chunker    │────►│  Qdrant      │
│ (sparse.pkl) │     │  (in docker) │     │  Retriever   │
└──────────────┘     └──────────────┘     └──────────────┘
                                                    │
                                           ┌────────┴────────┐
                                           ▼                ▼
                                    ┌────────────┐   ┌────────────┐
                                    │   REST     │   │    MCP     │
                                    │  (FastAPI) │   │  (FastMCP) │
                                    └────────────┘   └────────────┘
```

## Data Flow

1. `ingest.py` discovers `.md` files in `data/prepared/`
2. `chunker.py` parses each file: heading chain, code blocks, prose splitting, parent-child assignment
3. `embedder.Embedder` batches chunk text → fastembed (ONNX, GPU via CUDAExecutionProvider) → 384-dim dense vectors
4. `sparse_builder.py` builds TF-IDF sparse vectors over all chunk text
5. Qdrant stores: id, dense vector, sparse vector, payload (metadata + content + parent info)
6. `QdrantRetriever` loads sparse model at startup, queries via prefetch + Fusion.RRF at search time
7. Parent-child deduplication keeps highest-scoring child per parent section

## Embedding Model

- **Model:** `BAAI/bge-small-en-v1.5`
- **Dimensions:** 384
- **Provider:** fastembed-gpu (in-process, ONNX runtime, CUDAExecutionProvider)
- **Distance:** Cosine
- **GPU required:** Yes — container hard-fails on startup if CUDA is unavailable. Set `EMBEDDING_PROVIDERS=CPUExecutionProvider` for local dev without GPU.
- **Drift detection:** `.model_info.json` sidecar in `QDRANT_STORAGE_PATH/` (model name + dim). Verified on server startup via `QdrantRetriever.verify_embedding_model()`.

## Qdrant Storage

- **Mode:** Embedded (`QdrantClient(path=...)`) — no separate container needed
- **Vectors:** Named dense (`"dense"`) + sparse (`"sparse"`)
- **Sparse index:** `on_disk=True` for memory efficiency
- **RRF fusion:** Server-side via `prefetch` + `FusionQuery(fusion=Fusion.RRF)`
- **Payload:** All chunk metadata + content + parent-child fields

## Container

Single Docker image: `python:3.14-slim` + `uv`. Runs as non-root `lore` user. ~600-700MB (includes fastembed-gpu, onnxruntime-gpu, scikit-learn). Requires NVIDIA GPU passthrough via `nvidia-container-toolkit`.

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Single container | Simplicity, no inter-service networking |
| Qdrant embedded | No separate DB container, dense + sparse + RRF in one backend |
| In-process embeddings | fastembed (ONNX) eliminates external dependency, reduces latency |
| TF-IDF sparse vectors | BM25-like keyword search via scikit-learn, stored natively in Qdrant |
| Parent-child chunking | Small chunks for search precision, parent content for context |
| Atomic preparer publish | Ingest always sees consistent snapshot |
| Code-aware chunking | Preserves code block semantics for RAG |
