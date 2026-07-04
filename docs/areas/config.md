# Configuration

**File:** `docs_shared/config.py`

## Settings Dataclass

Frozen dataclass holding all runtime configuration. Single instance created via `Settings.from_env()` at module import.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `lm_studio_url` | `str` | `http://host.docker.internal:1234/v1` | LM Studio API base URL |
| `lm_studio_api_key` | `str` | `""` | Bearer token for LM Studio auth |
| `embedding_model` | `str` | `nomic-embed-text-v1.5` | Embedding model identifier |
| `embedding_dim` | `int` | `768` | Embedding vector dimension (for Qdrant collection creation) |
| `qdrant_storage_path` | `str` | `/data/qdrant_storage` | Qdrant embedded storage path |
| `qdrant_collection` | `str` | `docs` | Qdrant collection name |
| `rrf_k` | `int` | `60` | RRF fusion parameter |
| `prepared_dir` | `str` | `/data/prepared` | Prepared documents directory |
| `server_port` | `int` | `8000` | HTTP server port |
| `chunk_max_words` | `int` | `800` | Maximum words per chunk |
| `chunk_overlap_words` | `int` | `80` | Overlap words between prose chunks |
| `parent_level` | `int` | `2` | Heading level for parent section boundary |

## `lm_studio_headers` Property

Returns HTTP headers dict for LM Studio requests. If `lm_studio_api_key` is non-empty, returns `{"Authorization": "Bearer <key>"}`. Otherwise returns empty dict.

## `from_env()` Class Method

Reads all settings from environment variables with fallback defaults. All env var names are uppercased field names (e.g., `LM_STUDIO_URL`, `CHUNK_MAX_WORDS`). Integer fields are parsed with `int()`.

## Component Usage

| Component | Settings Used |
|-----------|---------------|
| `ingestion/embedder.py` | `lm_studio_url`, `lm_studio_headers` |
| `ingestion/ingest.py` | `prepared_dir`, `qdrant_storage_path`, `qdrant_collection`, `embedding_dim`, `chunk_max_words`, `chunk_overlap_words`, `parent_level` |
| `ingestion/sparse_builder.py` | none (standalone) |
| `docs_shared/retriever.py` | `qdrant_storage_path`, `qdrant_collection`, `embedding_model`, `lm_studio_url`, `lm_studio_headers` |
| `app/server.py` | `server_port`, `lm_studio_url`, `lm_studio_headers`, `embedding_model` |
| `preparers/` | Not used (host-side, reads from filesystem) |
