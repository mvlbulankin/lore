---
name: lore-server
description: Local RAG documentation server for Spark, Delta and other frameworks. Use to search documentation via REST API or MCP tools.
---

# Lore Server Skill

## Overview

Lore is a local RAG server that indexes framework documentation (Spark, Delta) and serves search via REST API and MCP. Uses hybrid retrieval: TF-IDF sparse + dense embeddings (local fastembed/ONNX) via Qdrant prefetch + Fusion.RRF.

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
3. **Verify:** `qdrant: true`, `sparse_model: true`, `collection_count > 0`

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/search` | Hybrid search (TF-IDF sparse + dense embeddings + RRF) |
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
    "id": 2234,
    "framework": "spark",
    "path": "pyspark-quickstart-dataframe.md",
    "title": "Quickstart: DataFrame",
    "heading": "Quickstart: DataFrame > DataFrame Creation",
    "chunk_index": 9,
    "score": 1.0,
    "snippet": "first 500 characters of matching content...",
    "parent_content": "first 2000 chars of parent section context"
  }
]
```

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Search returns wrong framework | Use `framework` parameter in request |
| Embed drift warning | Run `make down && make ingest-clear && make up` |
| Qdrant lock error | Run `make down`, then `make ingest-clear`, then `make up` |

## Best Practices

1. Always check `/health` before troubleshooting
2. Use `framework` parameter to narrow search scope
3. Keep `limit` reasonable (5-20) for relevance
4. After code changes to chunking, run `make ingest-clear`
5. Reindex after adding new source files: `make prepare && make down && make ingest-clear && make up`
