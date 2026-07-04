# Ingestion

**Files:** `ingestion/ingest.py`, `ingestion/chunker.py`, `ingestion/embedder.py`, `ingestion/bm25_index.py`

## Workflow (`ingest.py`)

```
discover → chunk → embed → upsert ChromaDB → build BM25
```

1. **Discover** — scan `PREPARED_DIR/{framework}/**/*.md`
2. **Chunk** — `make_chunks()` per file (code-aware, heading chain, metadata)
3. **Embed** — batch POST to LM Studio `/embeddings` (batch_size=32)
4. **Upsert** — `coll.upsert(ids, documents, metadatas, embeddings)` into ChromaDB
5. **BM25** — full rebuild `bm25_index.build(chunks)` → pickle to `BM25_PATH`

## Embedder

`embed_batch(texts, batch_size=32)`:
- Splits texts into batches of 32
- POSTs each batch to `{LM_STUDIO_URL}/embeddings`
- Uses shared `http_client` (3 retries, 60s timeout)
- Returns flat list of embedding vectors

## BM25 Index

`bm25_index.build(chunks)`:
- Tokenizes each chunk: `text.split()` → lowercase → strip
- Builds `BM25Okapi` over the tokenized corpus
- Pickles `{bm25, ids, meta}` to `BM25_PATH`
- **Always full rebuild** — no incremental merge

## Flags

| Flag | Effect |
|------|--------|
| `--framework <name>` | Index only the specified framework. BM25 still rebuilds for ALL frameworks to maintain consistency. |
| `--clear` | Delete all existing documents from the ChromaDB collection (collection itself is preserved). |

## Embedding Drift Detection

Two mechanisms check for embedding model changes at different pipeline stages. Both compare the `embedding_model` key stored in ChromaDB collection metadata against `settings.embedding_model`.

| Function | When | Module | Purpose |
|----------|------|--------|---------|
| `warn_if_embedding_drift()` | Ingest time | `docs_shared/guards.py` | Warns before upsert if model changed since last ingest |
| `verify_embedding_model()` | Server startup | `docs_shared/retriever.py` | Warns at query time if model changed since last ingest |

If either detects a mismatch, it logs `embedding_model_mismatch` with the stored vs configured model names and suggests `make ingest-clear`.

## Metadata Stored in ChromaDB

Each chunk stores:
- `framework`, `source_path`, `title`, `heading`, `chunk_index`
- `is_last_chunk`, `has_code`, `code_languages` (comma-joined), `block_types` (comma-joined)
