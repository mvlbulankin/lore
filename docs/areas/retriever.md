# Retriever

**Files:** `docs_shared/retriever.py`, `docs_shared/sparse_builder.py`, `docs_shared/embedder.py`

## Overview

`QdrantRetriever` orchestrates async hybrid search using Qdrant's prefetch + FusionQuery for server-side RRF, with parent-child deduplication.

## Initialization

```python
from docs_shared.embedder import Embedder
from docs_shared.retriever import QdrantRetriever

embedder = Embedder()
retriever = QdrantRetriever(embedder=embedder)
```

Creates an `AsyncQdrantClient(path=...)` (embedded mode) and loads the sparse TF-IDF model from disk. The embedder is passed in (local fastembed/ONNX inference).

## Async Methods

`search()`, `list_sources()`, `collection_count()`, `aclose()` are async. Use `await`.
`get_document()`, `verify_embedding_model()`, `is_sparse_model_loaded()` are sync.

## Hybrid Search (`search`)

1. **Dense query vector** — embed via fastembed (`self._embedder.embed_one(query)`)
2. **Sparse query vector** — encode via `SparseBuilder.encode_query()` (TF-IDF)
3. **Framework filter** — `Filter(must=[FieldCondition(key="framework", match=MatchValue(value=...))])`
4. **Prefetch** — two sub-queries (filter applied per-Prefetch for qdrant-client >= 1.18):
   - `Prefetch(query=dense_vec, using="dense", limit=fetch_limit, filter=qfilter)`
   - `Prefetch(query=sparse_vec, using="sparse", limit=fetch_limit, filter=qfilter)`
5. **Fusion** — `query=FusionQuery(fusion=Fusion.RRF)` (server-side RRF)
6. **Dedup** — `_dedup_by_parent()` keeps highest-scoring child per parent section

`fetch_limit = max(limit * settings.search_fetch_multiplier, settings.search_fetch_min)` to ensure enough candidates for deduplication.

## Parent-Child Deduplication (`_dedup_by_parent`)

After RRF fusion, multiple child chunks from the same parent section may appear in results.
Dedup keeps the highest-scoring child per `parent_id`, returning:
- `content` — the precise child chunk text (where the match was found)
- `parent_content` — the full parent section text (broader context)

Single-chunk sections have `parent_content = None` in the chunk, serialized as `""` in Qdrant payload. The retriever falls back to `content` when `parent_content` is empty.

## Methods

| Method | Description |
|--------|-------------|
| `search(query, framework?, limit=5)` | async. Hybrid search: dense + sparse -> prefetch + Fusion.RRF -> parent dedup -> top limit |
| `get_document(framework, path)` | Read `.md` from `prepared_dir/framework/path`. Path traversal protection. |
| `list_sources()` | async. Return `{framework: [source_paths]}` via Qdrant scroll (paginated, 1000 per page) |
| `collection_count()` | async. Return number of points in Qdrant collection |
| `verify_embedding_model()` | Read `.model_info.json` sidecar, compare with current settings. Returns `True` if consistent. |
| `is_sparse_model_loaded()` | Returns `True` if sparse (TF-IDF) model was loaded successfully |
| `aclose()` | async. Close AsyncQdrantClient |

## Error Handling

The retriever raises custom exceptions:

| Exception | When |
|-----------|------|
| `QdrantError` | Qdrant operation fails (in `collection_count`, `list_sources`) |
| `DocumentNotFoundError` | File not found in prepared directory or path traversal detected (in `get_document`) |

All exceptions inherit from `LoreError`.

## Hit Dataclass

```python
@dataclass
class Hit:
    id: int | str        # point ID
    framework: str
    source_path: str
    title: str
    heading: str         # "H1 > H2 > H3" chain
    chunk_index: int
    content: str         # child chunk (precise match)
    parent_content: str  # full parent section (context)
    score: float         # RRF score
```
