# Lore — Agent Instructions

Local RAG documentation server with MCP interface for AI agents.

## Architecture

One Docker container: ChromaDB (PersistentClient, in-process) + FastAPI (REST) + FastMCP. Hybrid retrieval: BM25 + Vector + RRF (k=60).

```
data/source/ → preparers/ → data/prepared/ → ingestion/ → ChromaDB + BM25
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
│   ├── chroma/                 # ChromaDB persistent storage
│   └── bm25.pkl                # BM25 index (generated)
├── docs_shared/                # shared package (workspace member)
│   ├── config.py               # Settings from env vars
│   ├── retriever.py            # HybridRetriever, BM25 + Vector + RRF
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
│   ├── chunker.py              # code-aware markdown chunker
│   ├── embedder.py             # batch embedding via LM Studio
│   ├── bm25_index.py           # BM25Okapi build + pickle
│   └── ingest.py               # main ingest workflow
├── app/
│   └── server.py               # FastAPI + FastMCP server
├── tests/
│   ├── conftest.py
│   ├── test_chunker.py         # 25 tests
│   └── test_preparer_base.py   # 16 tests
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
| `make ingest` | Index documents (ChromaDB + BM25) |
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
| `CHROMA_PERSIST_DIR` | ChromaDB storage path | `/data/chroma` |
| `CHROMA_COLLECTION` | ChromaDB collection name | `docs` |
| `RRF_K` | RRF fusion parameter | `60` |
| `PREPARED_DIR` | Prepared docs path | `/data/prepared` |
| `BM25_PATH` | BM25 index file path | `/data/bm25.pkl` |
| `SERVER_PORT` | Server port | `8000` |
| `CHUNK_MAX_WORDS` | Max words per chunk | `800` |
| `CHUNK_OVERLAP_WORDS` | Prose overlap words | `80` |

## Key Design Decisions

1. **One container** — no inter-service networking, simpler operations
2. **ChromaDB PersistentClient** — in-process, no separate DB container
3. **External embeddings** — LM Studio handles GPU, container stays lightweight
4. **BM25 full rebuild** — consistency guarantee, no incremental merge complexity
5. **Atomic preparer publish** — staging + rename, ingest always sees consistent snapshot
6. **Code-aware chunking** — code fences are atomic, heading chain in metadata
7. **Embedding drift detection** — warns at startup if model changed since last ingest

## REST API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/search` | Hybrid search. Body: `{query, framework?, limit}` |
| `GET` | `/sources` | List frameworks and documents |
| `GET` | `/docs/{framework}/{path}` | Get full document |
| `GET` | `/health` | Health check |

## MCP Tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `search_docs` | `query`, `framework?`, `limit=5` | Hybrid BM25+Vector search |
| `get_document` | `framework`, `path` | Read full document |
| `list_sources` | — | List indexed frameworks |

## Rules for Agents

- **DO NOT** modify `data/source/` — it is read-only raw documentation
- **DO NOT** run `make ingest` without confirmation — it requires LM Studio running
- **ALWAYS** run `make prepare` before `make ingest` when source files change
- **ALWAYS** run `make test` after code changes
- **ALWAYS** run `uv run ruff check` after Python changes
- **ALWAYS** run `make ingest-clear` after chunking logic changes
- **ALWAYS** restart container after `make ingest` (BM25 loads at startup)

## Documentation

Detailed per-component documentation in `docs/areas/`. See `docs/context-index.md` for navigation.

## Troubleshooting

See `docs/troubleshooting.md` for common issues and fixes.
