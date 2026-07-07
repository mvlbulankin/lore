# Ingestion

**Files:** `ingestion/ingest.py`, `ingestion/chunker.py`, `docs_shared/embedder.py`

## Logging

`main()` configures structlog with JSON output, ISO timestamps, and INFO level — consistent with the server's logging format.

## Workflow (`ingest.py`)

```
discover → chunk → pickle cache → TF-IDF fit → per-file: reload → embed → sparse → upsert
```

1. **Discover** — scan `PREPARED_DIR/{framework}/**/*.md` (all frameworks, regardless of `--framework` filter)
2. **Chunk** — `make_chunks()` per file, streamed to pickle cache on disk
3. **TF-IDF** — `SparseBuilder.fit_build(texts)` on all chunk texts, then free texts
4. **Qdrant init** — create collection if missing; optionally clear with `--clear`
5. **Save sparse model** — single write to `sparse_model.pkl`
6. **Per-file processing** — reload chunks from cache, embed via fastembed (local ONNX), build sparse, upsert to Qdrant
7. **Cleanup** — cache directory removed in `finally` block

## Embedder

`docs_shared.embedder.Embedder` (factory → `FastEmbedEmbedder`):
- Uses `fastembed.TextEmbedding` for local ONNX inference
- Model: configurable via `EMBEDDING_MODEL` env var (default: `BAAI/bge-small-en-v1.5`)
- `embed_sync(texts)` — sync batch embedding via ONNX runtime
- `embed(texts)` — async batch embedding (wraps sync via `asyncio.to_thread`)
- `embed_one(text)` — async single-text embedding
- One Embedder instance per ingest run, reused across all files
- First run downloads model from HuggingFace Hub to `HF_HOME`
- Model name comes from `settings.embedding_model` (env var `EMBEDDING_MODEL` via Settings)

## Memory Optimization

The ingest workflow constructs a single `Embedder` at startup and reuses it
across all files. Embeddings are computed one chunk at a time via
`embed_sync([chunk.content])` with an individual `client.upsert()` per chunk.
This intentionally avoids batch processing to prevent OOM on memory-constrained
machines — the trade-off is slower ingest speed for predictable memory usage.

Chunks are streamed to a pickle cache to avoid holding the entire corpus in RAM.

**Performance:** initial ingest on Ryzen 5 5600 / 16 GB RAM (RRD4) takes ~100 s.

## Chunk Pickle Cache

To avoid holding the entire corpus of chunks in RAM simultaneously, the ingest
workflow streams chunks to a pickle cache in `QDRANT_STORAGE_PATH/_chunks_cache/`
immediately after chunking. Only file paths (not chunk data) are kept in RAM.
During per-file processing, chunks are reloaded from disk via `pickle.loads()`,
and the cache file is deleted after consumption. The cache directory is cleaned up
in a `finally` block, ensuring no stale files remain after success or failure.

## Sparse Builder (TF-IDF)

`sparse_builder.SparseBuilder`:
- Uses `sklearn.feature_extraction.text.TfidfVectorizer` with `sublinear_tf=True` (BM25-like saturation)
- `fit_build(texts)` — fit on corpus, return list of `SparseVector(indices, values)`
- `encode_query(query)` — transform single query string to `SparseVector`
- `save(path)` / `load(path)` — joblib the fitted vectorizer for query-time reuse
- Saved to `QDRANT_STORAGE_PATH/sparse_model.pkl`

## Flags

| Flag | Effect |
|------|--------|
| `--framework <name>` | Index only the specified framework. Sparse model is rebuilt on all chunks. |
| `--clear` | Delete all points from the Qdrant collection, remove the sparse model and `.model_info.json`. |

## Embedding Drift Detection

After upsert, ingest writes `.model_info.json` to `QDRANT_STORAGE_PATH/` with `embedding_model` and `embedding_dim`.
On server startup, `QdrantRetriever.verify_embedding_model()` reads this sidecar and compares against current settings.
On mismatch, logs a warning and returns `False` (server still starts).
Cleared on `--clear` flag.

## Metadata Stored in Qdrant Payload

Each chunk stores:
- `framework`, `source_path`, `title`, `heading`, `chunk_index`
- `is_last_chunk`, `has_code`, `code_languages` (comma-joined), `block_types` (comma-joined)
- `content` — full chunk text (needed for `_dedup_by_parent` in retriever)
- `parent_id` — `"framework/path/H1 > H2"` parent section identifier
- `parent_heading` — heading chain of the parent section
- `parent_content` — full text of all child chunks in the same parent section (empty for single-chunk sections)

## Important: Ingest vs. Server

Qdrant is embedded (in-process). The ingest script and the server **cannot run simultaneously** — they both try to lock the same Qdrant storage directory. Workflow:

```bash
make down              # stop server (releases Qdrant lock)
make ingest-clear      # run ingest (acquires lock)
make up                # start server (acquires lock)
```

## Security Note: Pickle Cache

`pickle` is used in `ingestion/ingest.py` to write the chunks cache (`_chunks_cache/`). The cache is regenerated every ingest run from trusted chunking output — never from untrusted input. If the cache directory is ever shared with a multi-user system, replace `pickle` with `json` (chunk content is JSON-serializable after dataclass conversion).
