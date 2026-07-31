# Architecture

## Pipeline

```
{framework}-docs-extractor/  ──►  data/docs/  ──►  ingestion  ──►  Qdrant
      (host, uv)                (clean .md)       (docker)         (search index)
```

1. **Extractors** — external repos (`delta-docs-extractor/`, `pyspark-docs-extractor/`) fetch raw documentation and produce clean Markdown. Run on host via `uv`.
2. **Docs** — clean `.md` files in `data/docs/{framework}/`. Copied from extractor output by `make prepare-{framework}`.
4. **Ingestion** — runs in Docker container: chunks, embeds locally (fastembed/ONNX), builds TF-IDF sparse vectors, upserts to Qdrant.
5. **Search** — server queries Qdrant (dense + sparse vectors), fuses with server-side RRF, deduplicates by parent section.

## Component Interaction

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  FastEmbed   │◄────│   Embedder   │────►│    Qdrant    │
│  (ONNX CPU)  │     │  (in docker) │     │  (embedded)  │
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

1. `ingest.py` discovers `.md` files in `data/docs/`
2. `chunker.py` parses each file: heading chain, code blocks, prose splitting, parent-child assignment
3. Chunks streamed to pickle cache on disk
4. `sparse_builder.py` builds TF-IDF sparse vectors over all chunk text
5. Per-framework: reload chunks from cache, embed via fastembed (local ONNX), build sparse, upsert to Qdrant
6. `QdrantRetriever` loads sparse model at startup, queries via prefetch + Fusion.RRF at search time
7. Parent-child deduplication keeps highest-scoring child per parent section

## Embedding Model

- **Provider:** FastEmbedEmbedder (local ONNX inference via `fastembed`)
- **Model:** `BAAI/bge-small-en-v1.5` (configurable via `EMBEDDING_MODEL`)
- **Dimension:** 384 (configurable via `EMBEDDING_DIM`)
- **Distance:** Cosine
- **GPU required:** No — runs on CPU via ONNX runtime
- **Model cache:** HuggingFace Hub, cached at `HF_HOME=/data/hf_cache`
- **Drift detection:** `.model_info.json` sidecar in `QDRANT_STORAGE_PATH/` (model name + dim). Verified on server startup via `QdrantRetriever.verify_embedding_model()`.

## Qdrant Storage

- **Mode:** Embedded (`QdrantClient(path=...)`) — no separate container needed
- **Vectors:** Named dense (`"dense"`) + sparse (`"sparse"`)
- **Sparse index:** `on_disk=True` for memory efficiency
- **RRF fusion:** Server-side via `prefetch` + `FusionQuery(fusion=Fusion.RRF)`
- **Payload:** All chunk metadata + content + parent-child fields

## Container

Single Docker image: `python:3.14-slim` + `uv`. Runs as non-root `lore` user. ~890MB (includes fastembed, ONNX runtime, scikit-learn).

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Single container | Simplicity, no inter-service networking |
| Qdrant embedded | No separate DB container, dense + sparse + RRF in one backend |
| Local embeddings | fastembed/ONNX — no external API, no GPU required, self-contained |
| TF-IDF sparse vectors | BM25-like keyword search via scikit-learn, stored natively in Qdrant |
| Parent-child chunking | Small chunks for search precision, parent content for context |
| External extractors | Each framework's extraction logic is independently versioned and tested |
| Code-aware chunking | Preserves code block semantics for RAG |
| Pickle chunk cache | Avoids holding entire corpus in RAM during ingest |
