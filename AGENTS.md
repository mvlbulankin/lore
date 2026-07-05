# Lore — Agent Instructions

Local RAG documentation server with MCP interface for AI agents.

## Architecture

One Docker container: Qdrant (embedded, in-process) + FastAPI (REST) + FastMCP. Dense embeddings via local fastembed/ONNX (no external API, no GPU). TF-IDF sparse vectors via scikit-learn. Hybrid retrieval: dense + sparse + RRF fusion (server-side).

```
data/source/ → preparers/ → data/prepared/ → ingestion/ → Qdrant (dense + sparse)
```

## Project Structure

```
lore/
├── docker-compose.yml          # single service, port 8000
├── Dockerfile                  # python:3.14-slim + uv, runs as lore user
├── .env.example                # template for .env
├── .python-version             # 3.14
├── Makefile                    # all commands
├── pyproject.toml              # uv workspace root
├── uv.lock                     # lock file
├── data/
│   ├── source/                 # raw docs (Jekyll, MDX, Python) — READ-ONLY
│   │   ├── spark/docs/
│   │   ├── delta/docs/
│   │   ├── delta/examples/
│   │   └── test/
│   ├── prepared/               # output of preparers (clean .md)
│   └── qdrant_storage/         # Qdrant embedded storage + sparse model
├── docs_shared/                # shared package (workspace member)
│   ├── config.py               # Settings from env vars
│   ├── exceptions.py           # Custom exception hierarchy
│   ├── logging.py              # Shared structlog configuration
│   ├── embedder.py             # FastEmbedEmbedder (local ONNX via fastembed)
│   ├── retriever.py            # QdrantRetriever, async, dense + sparse + RRF
│   └── sparse_builder.py       # TF-IDF → Qdrant sparse vectors
├── preparers/                  # host-side document preparation
│   ├── base.py                 # FrameworkPreparer Protocol
│   ├── registry.py             # auto-discovery
│   ├── cli.py                  # CLI entry point
│   ├── _atomic.py              # staging + atomic rename
│   ├── delta/prepare.py        # MDX + Python → MD
│   ├── spark/prepare.py        # Jekyll cleanup
│   └── test/prepare.py         # trivial copy
├── ingestion/                  # runs inside Docker container
│   ├── chunker.py              # code-aware markdown chunker (parent-child)
│   └── ingest.py               # main ingest workflow
├── app/
│   └── server.py               # FastAPI + FastMCP server
├── tests/
│   ├── conftest.py
│   ├── test_chunker.py         # 35 tests
│   ├── test_config.py          # 2 tests
│   ├── test_embedder.py        # 7 tests
│   ├── test_ingest.py          # 17 tests
│   ├── test_integration.py     # 7 tests
│   ├── test_mcp_tools.py       # 7 tests
│   ├── test_preparer_base.py   # 12 tests
│   ├── test_sparse_builder.py  # 6 tests
│   ├── test_retriever.py       # 8 tests
│   └── test_server.py          # 9 tests
├── docs/
│   ├── areas/                  # per-component documentation
│   │   ├── embedder.md
│   │   ├── retriever.md
│   │   ├── chunker.md
│   │   ├── preparers.md
│   │   ├── ingestion.md
│   │   ├── server.md
│   │   ├── config.md
│   │   └── docker.md
│   ├── architecture.md
│   ├── testing.md
│   ├── troubleshooting.md
│   └── context-index.md
├── plans/
│   └── fastembed-migration.md
└── skills/
    └── lore-server/SKILL.md    # external agent skill
```

## Commands

| Command | Description |
|---------|-------------|
| `make install` | Install dependencies (`uv sync`) |
| `make lock` | Generate lock file (`uv lock`) |
| `make up` | Start container |
| `make rebuild` | Start container with fresh build |
| `make down` | Stop container |
| `make shell` | Bash shell inside container |
| `make prepare-dry-run` | Show what preparers will do |
| `make prepare` | Prepare all frameworks (source → prepared) |
| `make prepare-spark` | Prepare Spark only |
| `make prepare-delta` | Prepare Delta only |
| `make ingest` | Index documents (Qdrant dense + sparse) |
| `make ingest-clear` | Clear collection, then reindex |
| `make logs` | Container logs (follow) |
| `make test` | Run tests |
| `make clean` | Remove container, volumes, venv, prepared |

## Environment Variables

| Variable | Description | Default |
|---------|-------------|---------|
| `EMBEDDING_MODEL` | Embedding model name (fastembed-compatible) | `BAAI/bge-small-en-v1.5` |
| `EMBEDDING_DIM` | Embedding vector dimension | `384` |
| `QDRANT_STORAGE_PATH` | Qdrant embedded storage path | `/data/qdrant_storage` |
| `QDRANT_COLLECTION` | Qdrant collection name | `docs` |
| `PREPARED_DIR` | Prepared docs path | `/data/prepared` |
| `CHUNK_MAX_WORDS` | Max words per chunk | `800` |
| `CHUNK_OVERLAP_WORDS` | Prose overlap words | `80` |
| `PARENT_LEVEL` | Heading level for parent boundary | `2` |
| `SNIPPET_MAX_CHARS` | Max chars in search snippet | `500` |
| `PARENT_CONTENT_MAX_CHARS` | Max chars in parent context | `2000` |
| `SEARCH_FETCH_MULTIPLIER` | Fetch multiplier for dedup | `4` |
| `SEARCH_FETCH_MIN` | Minimum fetch for dedup | `20` |
| `CORS_ORIGINS` | CORS allowed origins (comma-separated) | `*` |

## Key Design Decisions

1. **One container** — no inter-service networking, simpler operations
2. **Qdrant embedded** — in-process, no separate DB container, dense + sparse + RRF in one
3. **Local embeddings** — FastEmbedEmbedder uses ONNX via fastembed, no external API or GPU needed
4. **TF-IDF sparse vectors** — BM25-like keyword search via scikit-learn, native in Qdrant
5. **Parent-child chunking** — small chunks for precision, parent content for context
6. **Atomic preparer publish** — staging + rename, ingest always sees consistent snapshot
7. **Code-aware chunking** — code fences are atomic, heading chain in metadata

## REST API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/search` | Hybrid search. Body: `{query, framework?, limit}`. Returns `snippet` + `parent_content`. |
| `GET` | `/sources` | List frameworks and documents |
| `GET` | `/docs/{framework}/{path:path}` | Get full document |
| `GET` | `/health` | Health check |

## MCP Tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `search_docs` | `query`, `framework?`, `limit=5` | Hybrid dense+sparse search with RRF fusion |
| `get_document` | `framework`, `path` | Read full document |
| `list_sources` | — | List indexed frameworks |

## Security

1. **Pickle** is used only for self-generated cache (`_chunks_cache/`). Cache is regenerated every ingest run from trusted chunking output — never from untrusted input.
2. **Path traversal** is blocked in `get_document`. Paths are resolved and checked to be within the prepared directory.
3. **CORS** defaults to `*` (permissive). Restrict via env in production.

## Rules for Agents

- **DO NOT** modify `data/source/` — it is read-only raw documentation
- **DO NOT** run `make ingest` without confirmation — needs server stopped (Qdrant lock)
- **ALWAYS** run `make prepare` before `make ingest` when source files change
- **ALWAYS** run `make test` after code changes
- **ALWAYS** run `make ruff` after Python changes (`ruff check --fix`)
- **ALWAYS** run `make ingest-clear` after chunking logic changes

## Documentation

Detailed per-component documentation in `docs/areas/`. See `docs/context-index.md` for navigation.

## Troubleshooting

See `docs/troubleshooting.md` for common issues and fixes.
