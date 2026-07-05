from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from fastapi.middleware.cors import CORSMiddleware

from fastmcp import FastMCP
from fastmcp.utilities.lifespan import combine_lifespans

from docs_shared.config import settings
from docs_shared.embedder import Embedder, EMBEDDING_MODEL
from docs_shared.logging import configure_logging
from docs_shared.retriever import QdrantRetriever, Hit
from docs_shared.exceptions import DocumentNotFoundError, QdrantError

configure_logging()
log = structlog.get_logger()

mcp = FastMCP("lore")
mcp_app = mcp.http_app(path="/")


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


app = FastAPI(
    title="Docs API",
    lifespan=combine_lifespans(app_lifespan, mcp_app.lifespan),
)
app.mount("/mcp", mcp_app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def get_retriever() -> QdrantRetriever:
    return app.state.retriever


class SearchRequest(BaseModel):
    query: str
    framework: str | None = None
    limit: int = Field(default=5, ge=1, le=100)


def _to_hit_dict(hits: list[Hit]) -> list[dict[str, Any]]:
    return [
        {
            "id": h.id,
            "framework": h.framework,
            "path": h.source_path,
            "title": h.title,
            "heading": h.heading,
            "chunk_index": h.chunk_index,
            "score": h.score,
            "snippet": h.content[: settings.snippet_max_chars],
            "parent_content": h.parent_content[: settings.parent_content_max_chars]
            if h.parent_content
            else None,
        }
        for h in hits
    ]


@mcp.tool()
async def search_docs(
    query: str, framework: str | None = None, limit: int = 5
) -> list[dict]:
    """Hybrid semantic + keyword search over documentation."""
    try:
        hits = await get_retriever().search(query, framework, limit)
        return _to_hit_dict(hits)
    except QdrantError as e:
        raise RuntimeError(f"Qdrant error: {e}") from e


@mcp.tool()
def get_document(framework: str, path: str) -> str:
    """Return full document content by path."""
    try:
        return get_retriever().get_document(framework, path)
    except DocumentNotFoundError:
        raise RuntimeError("Document not found")


@mcp.tool()
async def list_sources() -> dict[str, list[str]]:
    """List all available frameworks and documents."""
    try:
        return await get_retriever().list_sources()
    except QdrantError as e:
        raise RuntimeError(f"Qdrant error: {e}") from e


@app.post("/search")
async def search(req: SearchRequest) -> list[dict]:
    try:
        retriever = get_retriever()
        hits = await retriever.search(req.query, req.framework, req.limit)
        return _to_hit_dict(hits)
    except QdrantError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sources")
async def sources() -> dict[str, list[str]]:
    try:
        return await get_retriever().list_sources()
    except QdrantError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/docs/{framework}/{path:path}")
def get_doc(framework: str, path: str) -> str:
    try:
        return get_retriever().get_document(framework, path)
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found")


@app.get("/health")
async def health() -> dict:
    retriever = get_retriever()
    qdrant_ok = False
    count = 0
    try:
        count = await retriever.collection_count()
        qdrant_ok = count >= 0
    except Exception as e:
        log.warning("health_qdrant_check_failed", error=str(e))

    sparse_ok = retriever.is_sparse_model_loaded()

    return {
        "qdrant": qdrant_ok,
        "sparse_model": sparse_ok,
        "collection_count": count,
        "embedding_model": EMBEDDING_MODEL,
    }
