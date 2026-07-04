# Retriever

**File:** `docs_shared/retriever.py`

## Overview

`QdrantRetriever` orchestrates hybrid search using Qdrant's prefetch + FusionQuery for server-side RRF, with parent-child deduplication.

## Initialization

```python
retriever = QdrantRetriever()
```

Creates a `QdrantClient(path=...)` (embedded mode), and loads the sparse TF-IDF model from disk.

## Hybrid Search (`search`)

1. **Dense query vector** — embed via LM Studio POST to `{LM_STUDIO_URL}/embeddings`
2. **Sparse query vector** — encode via `SparseBuilder.encode_query()` (TF-IDF)
3. **Framework filter** — `Filter(must=[FieldCondition(key="framework", match=MatchValue(value=...))])`
4. **Prefetch** — two sub-queries:
   - `Prefetch(query=dense_vec, using="dense", limit=fetch_limit)`
   - `Prefetch(query=sparse_vec, using="sparse", limit=fetch_limit)`
5. **Fusion** — `query=FusionQuery(fusion=Fusion.RRF)` (server-side RRF)
6. **Dedup** — `_dedup_by_parent()` keeps highest-scoring child per parent section

`fetch_limit = max(limit * 4, 20)` to ensure enough candidates for deduplication.

## Parent-Child Deduplication (`_dedup_by_parent`)

After RRF fusion, multiple child chunks from the same parent section may appear in results.
Dedup keeps the highest-scoring child per `parent_id`, returning:
- `content` — the precise child chunk text (where the match was found)
- `parent_content` — the full parent section text (broader context)

Single-chunk sections have `parent_content = ""` in payload, which falls back to `content`.

## Embedding (`_embed`)

- Uses shared `http_client` (httpx with 3 retries, 60s timeout).
- Sends batch to LM Studio OpenAI-compatible `/embeddings` endpoint.
- Returns list of embedding vectors.

## Methods

| Method | Description |
|--------|-------------|
| `search(query, framework?, limit=5)` | Hybrid search: dense + sparse → prefetch + Fusion.RRF → parent dedup → top limit |
| `get_document(framework, path)` | Read `.md` from `prepared_dir/framework/path` |
| `list_sources()` | Return `{framework: [source_paths]}` via Qdrant scroll |
| `collection_count()` | Return number of points in Qdrant collection |
| `verify_embedding_model()` | No-op (Qdrant doesn't store custom collection metadata) |

## Hit Dataclass

```python
@dataclass
class Hit:
    id: str            # point ID
    framework: str
    source_path: str
    title: str
    heading: str       # "H1 > H2 > H3" chain
    chunk_index: int
    content: str       # child chunk (precise match)
    parent_content: str  # full parent section (context)
    score: float       # RRF score
```
