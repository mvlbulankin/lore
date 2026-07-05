# Retriever

**Files:** `docs_shared/retriever.py`, `docs_shared/sparse_builder.py`, `docs_shared/embedder.py`

## Overview

`QdrantRetriever` orchestrates async hybrid search using Qdrant's prefetch + FusionQuery for server-side RRF, with parent-child deduplication.

## Initialization

```python
from docs_shared.embedder import Embedder
from docs_shared.retriever import QdrantRetriever

embedder = Embedder(cache_dir="/data/fastembed_cache")
retriever = QdrantRetriever(embedder=embedder)
```

Creates an `AsyncQdrantClient(path=...)` (embedded mode) and loads the sparse TF-IDF model from disk. The embedder is passed in (in-process ONNX, no HTTP calls).

## Async Methods

`search()`, `list_sources()`, `collection_count()` are async. Use `await`.
`get_document()` and `verify_embedding_model()` remain sync (filesystem operations).

Close resources on shutdown: `await retriever.aclose()`

## Hybrid Search (`search`)

1. **Dense query vector** — embed via in-process fastembed (`self._embedder.embed_one(query)`)
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

## Methods

| Method | Description |
|--------|-------------|
| `search(query, framework?, limit=5)` | async. Hybrid search: dense + sparse -> prefetch + Fusion.RRF -> parent dedup -> top limit |
| `get_document(framework, path)` | Read `.md` from `prepared_dir/framework/path` |
| `list_sources()` | async. Return `{framework: [source_paths]}` via Qdrant scroll |
| `collection_count()` | async. Return number of points in Qdrant collection |
| `verify_embedding_model()` | Read `.model_info.json` sidecar, compare with current settings. Returns `True` if consistent. |
| `aclose()` | async. Close AsyncQdrantClient |

## Error Handling

The retriever raises custom exceptions:

| Exception | When |
|-----------|------|
| `QdrantError` | Qdrant operation fails (in `collection_count`, `list_sources`) |
| `DocumentNotFoundError` | File not found in prepared directory (in `get_document`) |

All exceptions inherit from `LoreError`.

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
