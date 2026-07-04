# Architecture

## Pipeline

```
data/source/  ──►  preparers/  ──►  data/prepared/  ──►  ingestion  ──►  ChromaDB + BM25
   (raw)          (host, uv)        (clean .md)         (docker)         (search index)
```

1. **Source** — raw documentation in framework-specific formats (Jekyll, MDX, Python)
2. **Preparers** — per-framework transformers that clean and normalize to standard Markdown. Runs on host via `uv`.
3. **Prepared** — clean `.md` files in `data/prepared/{framework}/`. Atomic publish via staging + rename.
4. **Ingestion** — runs in Docker container: chunks, embeds, upserts to ChromaDB, builds BM25 index.
5. **Search** — server queries ChromaDB (vector) + BM25 (keyword), fuses with RRF.

## Component Interaction

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   LM Studio  │◄────│   Embedder   │────►│   ChromaDB   │
│  (host:1234) │     │  (in docker) │     │ Persistent   │
└──────────────┘     └──────────────┘     └──────────────┘
                                │                    │
                                ▼                    ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  BM25 Index  │◄────│   Chunker    │────►│  Hybrid      │
│ (bm25.pkl)   │     │  (in docker) │     │  Retriever   │
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
2. `chunker.py` parses each file: heading chain, code blocks, prose splitting
3. `embedder.py` batches chunk text → LM Studio → 768-dim vectors
4. ChromaDB stores: id, document text, metadata, embedding vector
5. `bm25_index.py` builds `BM25Okapi` over all chunk text → pickled to disk
6. `HybridRetriever` loads BM25 at startup, queries both indexes at search time

## Embedding Model

- **Model:** `nomic-embed-text-v1.5`
- **Dimensions:** 768
- **Provider:** LM Studio (local, OpenAI-compatible API)
- **Distance:** Cosine (`hnsw:space: cosine`)
- **Drift detection:** Compares `embedding_model` in collection metadata at startup

## Container

Single Docker image: `python:3.14-slim` + `uv`. Non-root user. ~360MB.

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Single container | Simplicity, no inter-service networking |
| ChromaDB PersistentClient | No separate DB container, in-process persistence |
| External embeddings | LM Studio handles GPU, container stays lightweight |
| BM25 full rebuild | Consistency guarantee, simpler than incremental merge |
| Atomic preparer publish | Ingest always sees consistent snapshot |
| Code-aware chunking | Preserves code block semantics for RAG |
