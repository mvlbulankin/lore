# Configuration

**File:** `docs_shared/config.py`

## Settings Dataclass

Pydantic settings loaded from environment variables. Single instance created at module import.
Reads `.env` file automatically when present.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `embedding_model` | `str` | `BAAI/bge-small-en-v1.5` | Embedding model identifier (fastembed-compatible) |
| `embedding_dim` | `int` | `384` | Embedding vector dimension (for Qdrant collection creation) |
| `qdrant_storage_path` | `str` | `/data/qdrant_storage` | Qdrant embedded storage path |
| `qdrant_collection` | `str` | `docs` | Qdrant collection name |
| `prepared_dir` | `str` | `/data/docs` | Framework documentation directory |
| `chunk_max_words` | `int` | `800` | Maximum words per chunk |
| `chunk_overlap_words` | `int` | `80` | Overlap words between prose chunks (must be < `chunk_max_words`) |
| `parent_level` | `int` | `2` | Heading level for parent section boundary |
| `snippet_max_chars` | `int` | `500` | Max characters in search result snippet |
| `parent_content_max_chars` | `int` | `2000` | Max characters in parent context |
| `search_fetch_multiplier` | `int` | `4` | Fetch multiplier for dedup |
| `search_fetch_min` | `int` | `20` | Minimum fetch for dedup |
| `cors_origins` | `str` | `*` | CORS allowed origins (comma-separated) |

## Validation

A `model_validator` ensures `chunk_overlap_words < chunk_max_words`. Invalid config raises `ValueError` at import time.

## Component Usage

| Component | Settings Used |
|-----------|---------------|
| `docs_shared/embedder.py` | `embedding_model` (via `EMBEDDING_MODEL` constant) |
| `ingestion/ingest.py` | `prepared_dir`, `qdrant_storage_path`, `qdrant_collection`, `embedding_dim`, `chunk_max_words`, `chunk_overlap_words`, `parent_level` |
| `docs_shared/sparse_builder.py` | none (standalone) |
| `docs_shared/retriever.py` | `qdrant_storage_path`, `qdrant_collection`, `embedding_model`, `embedding_dim`, `search_fetch_multiplier`, `search_fetch_min` |
| `app/server.py` | `snippet_max_chars`, `parent_content_max_chars`, `cors_origins` |
| `delta-docs-extractor/` | Not used (external, host-side) |

## Additional Env Vars (not in Settings)

| Variable | Description |
|----------|-------------|
| `HF_HOME` | HuggingFace model cache directory (default: `/data/hf_cache` in container) |
