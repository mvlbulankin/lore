# Retriever

**File:** `docs_shared/retriever.py`

## Overview

`HybridRetriever` orchestrates BM25 keyword search, ChromaDB vector search, and RRF fusion to produce ranked search results.

## Initialization

```python
retriever = HybridRetriever()
```

Creates a `chromadb.PersistentClient`, opens/creates the collection with `embedding_function=None` (embeddings are computed externally via LM Studio), and loads the BM25 index from disk.

## BM25 Search (`_bm25_search`)

- Loads `BM25Okapi` from `data/bm25.pkl` at startup.
- Tokenization: `text.split()` → lowercase → strip.
- Computes per-document BM25 scores, filters by `framework` if specified, returns top-k `Hit` objects.
- If BM25 index is missing, returns empty list (logged as warning).

## Vector Search (`_vector_search`)

- Embeds query via `_embed()` → POST to `{LM_STUDIO_URL}/embeddings`.
- Queries ChromaDB with `where={"framework": ...}` filter if framework specified.
- Converts cosine distance to similarity: `max(0.0, 1.0 - distance)`.
- Returns top-k `Hit` objects.

## Embedding (`_embed`)

- Uses shared `http_client` (httpx with 3 retries, 60s timeout).
- Sends batch to LM Studio OpenAI-compatible `/embeddings` endpoint.
- Returns list of embedding vectors.

## RRF Fusion (`_rrf`)

Reciprocal Rank Fusion combines multiple ranked lists:

```
score(doc) = Σ 1 / (k + rank_i + 1)
```

With `k = RRF_K` (default 60). Higher score = better rank.

## Embedding Drift Detection (`verify_embedding_model`)

Compares `embedding_model` from collection metadata against `settings.embedding_model`. If mismatch, logs warning with hint to run `make ingest-clear`.

## Methods

| Method | Description |
|--------|-------------|
| `search(query, framework?, limit=5)` | Hybrid search: BM25(20) + Vector(20) → RRF → top limit |
| `get_document(framework, path)` | Read `.md` from `prepared_dir/framework/path` |
| `list_sources()` | Return `{framework: [source_paths]}` from ChromaDB metadata |
| `collection_count()` | Return number of documents in ChromaDB collection |
| `reload_bm25()` | Reload BM25 index from disk |

## Hit Dataclass

```python
@dataclass
class Hit:
    id: str            # "framework/source_path/chunk_index"
    framework: str
    source_path: str
    title: str
    heading: str       # "H1 > H2 > H3" chain
    chunk_index: int
    content: str
    score: float
```
