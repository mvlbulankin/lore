# Lore — Agent Instructions

Local RAG documentation server with MCP interface for AI agents.

## Architecture

One Docker container: Qdrant (embedded, in-process) + FastAPI (REST) + FastMCP. Hybrid retrieval: dense vectors + TF-IDF sparse vectors + RRF fusion (server-side).

```
data/source/ → preparers/ → data/prepared/ → ingestion/ → Qdrant (dense + sparse)
```

## Project Structure

```
lore/
├── docker-compose.yml          # single service, port 8000
├── Dockerfile                  # python:3.14-slim + uv, runs as root
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
│   ├── retriever.py            # QdrantRetriever, dense + sparse + RRF
│   └── guards.py               # embedding drift detection
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
│   ├── embedder.py             # batch embedding via LM Studio
│   ├── sparse_builder.py       # TF-IDF → Qdrant sparse vectors
│   └── ingest.py               # main ingest workflow
├── app/
│   └── server.py               # FastAPI + FastMCP server
├── tests/
│   ├── conftest.py
│   ├── test_chunker.py         # 31 tests
│   ├── test_preparer_base.py   # 16 tests
│   ├── test_sparse_builder.py  # 6 tests
│   └── test_retriever.py       # 5 tests
├── docs/
│   ├── areas/                  # per-component documentation
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
|----------|-------------|---------|
| `LM_STUDIO_URL` | LM Studio API URL | `http://host.docker.internal:1234/v1` |
| `LM_STUDIO_API_KEY` | LM Studio Bearer token | (empty) |
| `EMBEDDING_MODEL` | Embedding model name | `nomic-embed-text-v1.5` |
| `EMBEDDING_DIM` | Embedding vector dimension | `768` |
| `QDRANT_STORAGE_PATH` | Qdrant embedded storage path | `/data/qdrant_storage` |
| `QDRANT_COLLECTION` | Qdrant collection name | `docs` |
| `RRF_K` | RRF fusion parameter | `60` |
| `PREPARED_DIR` | Prepared docs path | `/data/prepared` |
| `SERVER_PORT` | Server port | `8000` |
| `CHUNK_MAX_WORDS` | Max words per chunk | `800` |
| `CHUNK_OVERLAP_WORDS` | Prose overlap words | `80` |
| `PARENT_LEVEL` | Heading level for parent boundary | `2` |

## Key Design Decisions

1. **One container** — no inter-service networking, simpler operations
2. **Qdrant embedded** — in-process, no separate DB container, dense + sparse + RRF in one
3. **External embeddings** — LM Studio handles GPU, container stays lightweight
4. **TF-IDF sparse vectors** — BM25-like keyword search via scikit-learn, native in Qdrant
5. **Parent-child chunking** — small chunks for precision, parent content for context
6. **Atomic preparer publish** — staging + rename, ingest always sees consistent snapshot
7. **Code-aware chunking** — code fences are atomic, heading chain in metadata

## REST API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/search` | Hybrid search. Body: `{query, framework?, limit}`. Returns `snippet` + `parent_content`. |
| `GET` | `/sources` | List frameworks and documents |
| `GET` | `/docs/{framework}/{path}` | Get full document |
| `GET` | `/health` | Health check |

## MCP Tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `search_docs` | `query`, `framework?`, `limit=5` | Hybrid dense+sparse search with RRF fusion |
| `get_document` | `framework`, `path` | Read full document |
| `list_sources` | — | List indexed frameworks |

## Rules for Agents

- **DO NOT** modify `data/source/` — it is read-only raw documentation
- **DO NOT** run `make ingest` without confirmation — it requires LM Studio running
- **ALWAYS** run `make prepare` before `make ingest` when source files change
- **ALWAYS** run `make test` after code changes
- **ALWAYS** run `uv run ruff check` after Python changes
- **ALWAYS** run `make ingest-clear` after chunking logic changes

## Documentation

Detailed per-component documentation in `docs/areas/`. See `docs/context-index.md` for navigation.

## Troubleshooting

See `docs/troubleshooting.md` for common issues and fixes.
