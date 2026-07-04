---
name: lore-server
description: Local RAG documentation server for Spark, Delta and other frameworks. Use to search documentation via REST API or MCP tools.
---

# Lore Server Skill

## Overview

Lore is a local RAG server that indexes framework documentation (Spark, Delta) and serves search via REST API and MCP. Uses hybrid retrieval: BM25 keyword + ChromaDB vector, fused with RRF.

## When to Use

- Need to look up Spark SQL, DataFrame API, Delta Lake documentation
- Searching for code examples, API references, or configuration guides
- Building features that reference framework documentation

## When NOT to Use

- General programming questions not related to indexed frameworks
- Questions about frameworks not yet indexed (check `/sources` first)
- When the server is not running (check `/health` first)

## Server Lifecycle

1. **Check health:** `curl http://localhost:8000/health`
2. **Start server:** `make up` (if not running)
3. **Verify:** `chroma: true`, `bm25_loaded: true`, `collection_count > 0`

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/search` | Hybrid search (BM25 + Vector + RRF) |
| `GET` | `/sources` | List available frameworks and documents |
| `GET` | `/docs/{framework}/{path}` | Get full document content |
| `GET` | `/health` | Server health check |

## Example Usage

### Search

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "DataFrame join operations", "framework": "spark", "limit": 5}'
```

### List Sources

```bash
curl http://localhost:8000/sources
```

### Get Document

```bash
curl http://localhost:8000/docs/spark/sql-programming-guide.md
```

## Response Format

Search returns an array of hits:

```json
[
  {
    "id": "spark/docs/sql.md/3",
    "framework": "spark",
    "path": "docs/sql.md",
    "title": "Spark SQL",
    "heading": "Spark SQL > DataFrame API > Joins",
    "chunk_index": 3,
    "score": 0.42,
    "snippet": "first 500 characters of matching content..."
  }
]
```

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Empty results after ingest | Restart container: `make down && make up` |
| `lm_studio: false` | Start LM Studio, verify API key in `.env` |
| Search returns wrong framework | Use `framework` parameter in request |
| `host.docker.internal` not resolving | Use host IP address in `LM_STUDIO_URL` |
| Embed drift warning | Run `make ingest-clear` |

## Best Practices

1. Always check `/health` before troubleshooting
2. Use `framework` parameter to narrow search scope
3. Keep `limit` reasonable (5-20) for relevance
4. After code changes to chunking, run `make ingest-clear`
5. Reindex after adding new source files: `make prepare && make ingest`
