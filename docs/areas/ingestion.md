# Ingestion

**Files:** `ingestion/ingest.py`, `ingestion/chunker.py`, `docs_shared/embedder.py`

## Logging

`main()` configures structlog with JSON output, ISO timestamps, and INFO level — consistent with the server's logging format.

## Workflow (`ingest.py`)

```
discover → chunk → pickle cache → TF-IDF fit → per-fw: reload → embed → sparse → upsert
```

1. **Discover** — scan `PREPARED_DIR/{framework}/**/*.md`
2. **Chunk** — `make_chunks()` per file, streamed to pickle cache on disk
3. **TF-IDF** — `SparseBuilder.fit_build(texts)` on all chunk texts, then free texts
4. **Per-framework** — reload chunks from cache, embed, build sparse, upsert to Qdrant
5. **Cleanup** — cache directory removed in `finally` block

## Embedder

`docs_shared/embedder.Embedder`:
- Uses `fastembed.TextEmbedding` (ONNX runtime, no PyTorch)
- Default model: `BAAI/bge-small-en-v1.5` (384 dims)
- Default batch_size: 64
- Providers: `CUDAExecutionProvider` (default, hard-fail if GPU absent). Override via `EMBEDDING_PROVIDERS` env var (comma-separated).
- `embed_sync(texts)` — sync batch embedding, thread-safe via internal lock
- `embed(texts)` — async batch embedding (runs in executor)
- `embed_one(text)` — async single-text embedding
- Model downloaded on first use, cached in `/data/fastembed_cache` (mounted volume)
- One Embedder instance per ingest run, reused across all frameworks

## Memory Optimization

The ingest workflow constructs a single `Embedder` at startup and reuses it
across all frameworks. Embeddings are computed in one batch call per framework
(`embed_sync([c.content for c in fw_chunks])`) rather than per-chunk, avoiding
the OOM caused by repeatedly constructing ONNX `InferenceSession` objects.

## Chunk Pickle Cache

To avoid holding the entire corpus of chunks in RAM simultaneously, the ingest
workflow streams chunks to a pickle cache in `QDRANT_STORAGE_PATH/_chunks_cache/`
immediately after chunking. Only file paths (not chunk data) are kept in RAM.
During per-framework processing, chunks are reloaded from disk via `pickle.loads()`,
and the cache file is deleted after consumption. The cache directory is cleaned up
in a `finally` block, ensuring no stale files remain after success or failure.

## Sparse Builder (TF-IDF)

`sparse_builder.SparseBuilder`:
- Uses `sklearn.feature_extraction.text.TfidfVectorizer` with `sublinear_tf=True` (BM25-like saturation)
- `fit_build(texts)` — fit on corpus, return list of `SparseVector(indices, values)`
- `encode_query(query)` — transform single query string to `SparseVector`
- `save(path)` / `load(path)` — pickle the fitted vectorizer for query-time reuse
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

## Security Note: Pickle Cache

`pickle` is used in `ingestion/ingest.py` to write the chunks cache (`_chunks_cache/`). The cache is regenerated every ingest run from trusted chunking output — never from untrusted input. If the cache directory is ever shared with a multi-user system, replace `pickle` with `json` (chunk content is JSON-serializable after dataclass conversion).
