# Server

**File:** `app/server.py`

## Architecture

Single FastAPI application that mounts FastMCP at `/mcp`. Both MCP tools and REST endpoints share the same `HybridRetriever` instance.

## Lifespan

```python
@asynccontextmanager
async def app_lifespan(app: FastAPI):
    yield
    shared_http_client.close()
```

Uses `combine_lifespans(app_lifespan, mcp_app.lifespan)` to manage both FastAPI and FastMCP lifecycles. On shutdown, closes the shared httpx client.

## Structlog

JSON-formatted logs with ISO timestamps, log levels, and exception info. Minimum level: INFO.

## MCP Tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `search_docs` | `query`, `framework?`, `limit=5` | Hybrid BM25+Vector search with RRF fusion |
| `get_document` | `framework`, `path` | Read full `.md` from prepared directory |
| `list_sources` | — | List all indexed frameworks and their source paths |

## REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/search` | Hybrid search. Body: `{query, framework?, limit}` |
| `GET` | `/sources` | List frameworks and documents |
| `GET` | `/docs/{framework}/{path:path}` | Get full document. The `:path` converter allows nested paths with slashes. |
| `GET` | `/health` | Health check |

## SearchRequest

```python
class SearchRequest(BaseModel):
    query: str
    framework: str | None = None
    limit: int = Field(default=5, ge=1, le=100)
```

## Health Response

```json
{
  "chroma": true,
  "lm_studio": true,
  "bm25_loaded": true,
  "collection_count": 1234,
  "embedding_model": "nomic-embed-text-v1.5"
}
```

## Hit Response Format

Each search result:
```json
{
  "id": "spark/docs/sql.md/3",
  "framework": "spark",
  "path": "docs/sql.md",
  "title": "Spark SQL",
  "heading": "Spark SQL > DataFrame API",
  "chunk_index": 3,
  "score": 0.42,
  "snippet": "first 500 chars of content"
}
```
