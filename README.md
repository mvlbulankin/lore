# Lore

[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/downloads/release/python-3140/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Local RAG documentation server with MCP interface for AI agents.

One Docker container: Qdrant (embedded, in-process) + FastAPI (REST) + FastMCP.
Embeddings via local fastembed/ONNX (no external API, no GPU).

## Architecture

| Layer | Solution |
|------|---------|
| Vector DB | Qdrant embedded `AsyncQdrantClient` (in-process) |
| Embedding | Local fastembed/ONNX (via fastembed, no GPU) |
| Retrieval | Hybrid: TF-IDF sparse + dense embeddings + RRF (server-side via Qdrant prefetch + FusionQuery) |
| Chunking | Code-aware: H1>H2>H3 chain, atomic code-fence, prose with overlap |
| Container | Single image ~500MB (python:3.14-slim + uv + ONNX runtime) |
| Pipeline | `{framework}-docs-extractor/` → `data/docs/` → `ingestion/` → Qdrant |

## Requirements

- **Docker** — for the lore container
- **uv** — Python package manager
- **Python 3.14**

## Quick Start

```bash
# 1. Configure .env
cp .env.example .env

# 2. Prepare documents
make prepare-delta
make prepare-spark

# 3. Start container
make up

# 4. Check health
curl http://localhost:8000/health

# 5. Ingest
make ingest

# 6. Search
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "your query", "framework": "spark", "limit": 5}'
```

## Commands

| Command | Description |
|---------|----------|
| `make install` | Install dependencies |
| `make up` | Start container |
| `make down` | Stop container |
| `make prepare-delta` | Run delta-lake-docs-extractor, copy to data/docs/delta/ |
| `make prepare-spark` | Run spark-docs-extractor, copy to data/docs/spark/ |
| `make ingest` | Index documents |
| `make ingest-clear` | Clear collection and reindex |
| `make test` | Run tests |
| `make logs` | Container logs |
| `make clean` | Remove container, volumes, venv |

## Documentation

| File | Description |
|------|----------|
| [docs/areas/embedder.md](docs/areas/embedder.md) | FastEmbedEmbedder, local ONNX |
| [docs/areas/retriever.md](docs/areas/retriever.md) | QdrantRetriever, hybrid dense+sparse, RRF, parent-child dedup |
| [docs/areas/chunker.md](docs/areas/chunker.md) | Code-aware chunking |
| [docs/areas/ingestion.md](docs/areas/ingestion.md) | Ingest workflow, embedder |
| [docs/areas/server.md](docs/areas/server.md) | FastAPI, FastMCP, endpoints |
| [docs/architecture.md](docs/architecture.md) | Detailed architecture |
| [docs/testing.md](docs/testing.md) | Tests |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Troubleshooting |

## MCP

Add to your MCP client configuration:

```json
{
  "mcp": {
    "lore": {
      "type": "remote",
      "url": "http://<server-ip>:8000/mcp",
      "enabled": true
    }
  }
}
```

Available tools: `search_docs`, `get_document`, `list_sources`.
