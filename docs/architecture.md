# Architecture

## Pipeline

```
data/source/  ──►  preparers/  ──►  data/prepared/  ──►  ingestion  ──►  Qdrant
   (raw)          (host, uv)        (clean .md)         (docker)         (search index)
```

1. **Source** — raw documentation in framework-specific formats (Jekyll, MDX, Python)
2. **Preparers** — per-framework transformers that clean and normalize to standard Markdown. Runs on host via `uv`.
3. **Prepared** — clean `.md` files in `data/prepared/{framework}/`. Atomic publish via staging + rename.
4. **Ingestion** — runs in Docker container: chunks, embeds, builds TF-IDF sparse vectors, upserts to Qdrant.
5. **Search** — server queries Qdrant (dense + sparse vectors), fuses with server-side RRF, deduplicates by parent section.

## Component Interaction

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   LM Studio  │◄────│   Embedder   │────►│    Qdrant    │
│  (host:1234) │     │  (in docker) │     │  (embedded)  │
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
3. `embedder.py` batches chunk text → LM Studio → 768-dim dense vectors
4. `sparse_builder.py` builds TF-IDF sparse vectors over all chunk text
5. Qdrant stores: id, dense vector, sparse vector, payload (metadata + content + parent info)
6. `QdrantRetriever` loads sparse model at startup, queries via prefetch + Fusion.RRF at search time
7. Parent-child deduplication keeps highest-scoring child per parent section

## Embedding Model

- **Model:** `nomic-embed-text-v1.5`
- **Dimensions:** 768
- **Provider:** LM Studio (local, OpenAI-compatible API)
- **Distance:** Cosine
- **Drift detection:** Currently no-op (Qdrant doesn't store custom collection metadata)

## Qdrant Storage

- **Mode:** Embedded (`QdrantClient(path=...)`) — no separate container needed
- **Vectors:** Named dense (`"dense"`) + sparse (`"sparse"`)
- **Sparse index:** `on_disk=True` for memory efficiency
- **RRF fusion:** Server-side via `prefetch` + `FusionQuery(fusion=Fusion.RRF)`
- **Payload:** All chunk metadata + content + parent-child fields

## Container

Single Docker image: `python:3.14-slim` + `uv`. Non-root user. ~400MB (includes scikit-learn).

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Single container | Simplicity, no inter-service networking |
| Qdrant embedded | No separate DB container, dense + sparse + RRF in one backend |
| External embeddings | LM Studio handles GPU, container stays lightweight |
| TF-IDF sparse vectors | BM25-like keyword search via scikit-learn, stored natively in Qdrant |
| Parent-child chunking | Small chunks for search precision, parent content for context |
| Atomic preparer publish | Ingest always sees consistent snapshot |
| Code-aware chunking | Preserves code block semantics for RAG |
