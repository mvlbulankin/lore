# Server

**File:** `app/server.py`

## Architecture

Single FastAPI application that mounts FastMCP at `/mcp`. Both MCP tools and REST endpoints share the same `QdrantRetriever` instance. Search endpoints are async.

## Lifespan

```python
@asynccontextmanager
async def app_lifespan(app: FastAPI):
    embedder = Embedder()
    retriever = QdrantRetriever(embedder=embedder)
    app.state.embedder = embedder
    app.state.retriever = retriever
    try:
        if not retriever.verify_embedding_model():
            log.error("embedding_model_drift_detected", hint="run: make ingest-clear")
        yield
    finally:
        await retriever.aclose()
```

Uses `combine_lifespans(app_lifespan, mcp_app.lifespan)` to manage both FastAPI and FastMCP lifecycles. On startup, creates embedder and retriever, verifies embedding model consistency. On shutdown, closes async retriever.

## Structlog

JSON-formatted logs with ISO timestamps, log levels, and exception info. Minimum level: INFO.

## MCP Tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `search_docs` | `query`, `framework?`, `limit=5` | async. Hybrid dense+sparse search with RRF fusion |
| `get_document` | `framework`, `path` | Read full `.md` from prepared directory |
| `list_sources` | — | async. List all indexed frameworks and their source paths |

MCP uses FastMCP's streamable HTTP transport at `/mcp/`. Session management via `Mcp-Session-Id` header.

## REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/search` | async. Hybrid search. Body: `{query, framework?, limit}` |
| `GET` | `/sources` | async. List frameworks and documents |
| `GET` | `/docs/{framework}/{path:path}` | Get full document. The `:path` converter allows nested paths with slashes. |
| `GET` | `/health` | async. Health check |

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
  "qdrant": true,
  "sparse_model": true,
  "collection_count": 3353,
  "embedding_model": "BAAI/bge-small-en-v1.5"
}
```

`/health` never returns 500 — all checks are wrapped in try/except with logging.

## Error Responses

| Endpoint | Exception | Status |
|----------|-----------|--------|
| `/search` | `QdrantError` | 500 |
| `/sources` | `QdrantError` | 500 |
| `/docs/...` | `DocumentNotFoundError` | 404 |

MCP tools raise `RuntimeError` with descriptive message on failure.

## Hit Response Format

Each search result:
```json
{
  "id": 2234,
  "framework": "spark",
  "path": "pyspark-quickstart-dataframe.md",
  "title": "Quickstart: DataFrame",
  "heading": "Quickstart: DataFrame > DataFrame Creation",
  "chunk_index": 9,
  "score": 1.0,
  "snippet": "first 500 chars of content",
  "parent_content": "first 2000 chars of parent section"
}
```
