from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from fastmcp import FastMCP
from fastmcp.utilities.lifespan import combine_lifespans

from docs_shared.retriever import HybridRetriever
from docs_shared.config import settings
from docs_shared import http_client as shared_http_client

structlog.configure(
    cache_logger_on_first_use=True,
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger("INFO"),
    logger_factory=structlog.PrintLoggerFactory(),
)

retriever = HybridRetriever()
retriever.verify_embedding_model()

mcp = FastMCP("lore")
mcp_app = mcp.http_app(path="/")

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    yield
    shared_http_client.close()

app = FastAPI(
    title="Docs API",
    lifespan=combine_lifespans(app_lifespan, mcp_app.lifespan),
)
app.mount("/mcp", mcp_app)

class SearchRequest(BaseModel):
    query: str
    framework: str | None = None
    limit: int = Field(default=5, ge=1, le=100)

def _to_hit_dict(hits) -> list[dict]:
    return [
        {
            "id": h.id,
            "framework": h.framework,
            "path": h.source_path,
            "title": h.title,
            "heading": h.heading,
            "chunk_index": h.chunk_index,
            "score": h.score,
            "snippet": h.content[:500],
        }
        for h in hits
    ]

@mcp.tool()
def search_docs(query: str, framework: str | None = None, limit: int = 5) -> list[dict]:
    """Hybrid semantic + keyword search over documentation."""
    hits = retriever.search(query, framework, limit)
    return _to_hit_dict(hits)

@mcp.tool()
def get_document(framework: str, path: str) -> str:
    """Return full document content by path."""
    return retriever.get_document(framework, path)

@mcp.tool()
def list_sources() -> dict[str, list[str]]:
    """List all available frameworks and documents."""
    return retriever.list_sources()

@app.post("/search")
def search(req: SearchRequest) -> list[dict]:
    hits = retriever.search(req.query, req.framework, req.limit)
    return _to_hit_dict(hits)

@app.get("/sources")
def sources() -> dict[str, list[str]]:
    return retriever.list_sources()

@app.get("/docs/{framework}/{path:path}")
def get_doc(framework: str, path: str) -> str:
    try:
        return retriever.get_document(framework, path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found")

@app.get("/health")
def health() -> dict:
    chroma_ok = retriever.collection_count() >= 0
    lm_ok = True
    try:
        shared_http_client.get(f"{settings.lm_studio_url}/models", headers=settings.lm_studio_headers, timeout=3).raise_for_status()
    except Exception:
        lm_ok = False
    return {
        "chroma": chroma_ok,
        "lm_studio": lm_ok,
        "bm25_loaded": retriever.bm25 is not None,
        "collection_count": retriever.collection_count(),
        "embedding_model": settings.embedding_model,
    }
