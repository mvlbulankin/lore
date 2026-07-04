# Ingestion

**Files:** `ingestion/ingest.py`, `ingestion/chunker.py`, `ingestion/embedder.py`, `ingestion/sparse_builder.py`

## Workflow (`ingest.py`)

```
discover → chunk → embed → sparse (TF-IDF) → upsert Qdrant
```

1. **Discover** — scan `PREPARED_DIR/{framework}/**/*.md`
2. **Chunk** — `make_chunks()` per file (code-aware, heading chain, metadata, parent-child)
3. **Embed** — batch POST to LM Studio `/embeddings` (batch_size=32)
4. **Sparse** — `SparseBuilder.fit_build(texts)` → TF-IDF sparse vectors
5. **Upsert** — `client.upsert(collection_name, points, wait=True)` into Qdrant (dense + sparse)

## Embedder

`embed_batch(texts, batch_size=32)`:
- Splits texts into batches of 32
- POSTs each batch to `{LM_STUDIO_URL}/embeddings`
- Uses shared `http_client` (3 retries, 60s timeout)
- Returns flat list of embedding vectors

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
| `--clear` | Delete all points from the Qdrant collection and remove the sparse model. |

## Embedding Drift Detection

NOTE: Qdrant doesn't store custom metadata on collection config like ChromaDB did.
`warn_if_embedding_drift()` is kept for compatibility but currently has no-op behavior.
Consider storing model info in a sidecar JSON file or payload on a special point.

## Metadata Stored in Qdrant Payload

Each chunk stores:
- `framework`, `source_path`, `title`, `heading`, `chunk_index`
- `is_last_chunk`, `has_code`, `code_languages` (comma-joined), `block_types` (comma-joined)
- `content` — full chunk text (needed for `_dedup_by_parent` in retriever)
- `parent_id` — `"framework/path/H1/H2"` parent section identifier
- `parent_heading` — heading chain of the parent section
- `parent_content` — full text of all child chunks in the same parent section (empty for single-chunk sections)
