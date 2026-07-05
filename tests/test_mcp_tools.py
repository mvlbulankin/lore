"""Tests for MCP tools (search_docs, get_document, list_sources)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docs_shared.exceptions import DocumentNotFoundError, QdrantError
from docs_shared.retriever import Hit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hit(
    framework: str = "spark",
    path: str = "docs/sql.md",
    content: str = "test content",
    score: float = 0.85,
) -> Hit:
    return Hit(
        id=f"{framework}/{path}/0",
        framework=framework,
        source_path=path,
        title="Test Doc",
        heading="Test Doc > Section",
        chunk_index=0,
        content=content,
        parent_content="parent context",
        score=score,
    )


# ---------------------------------------------------------------------------
# search_docs
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mcp_search_docs() -> None:
    """search_docs returns formatted list of dicts."""
    from app.server import search_docs

    hits = [_make_hit()]

    mock = MagicMock()
    mock.search = AsyncMock(return_value=hits)
    with patch("app.server.get_retriever", return_value=mock):
        result = await search_docs(query="test query", framework="spark", limit=5)

    assert isinstance(result, list)
    assert len(result) == 1
    h = result[0]
    assert h["id"] == "spark/docs/sql.md/0"
    assert h["framework"] == "spark"
    assert h["path"] == "docs/sql.md"
    assert h["score"] == 0.85
    assert "snippet" in h
    assert "parent_content" in h


@pytest.mark.anyio
async def test_mcp_search_docs_no_framework() -> None:
    """search_docs works without framework filter."""
    from app.server import search_docs

    hits = [_make_hit("spark"), _make_hit("delta", "docs/intro.md")]

    mock = MagicMock()
    mock.search = AsyncMock(return_value=hits)
    with patch("app.server.get_retriever", return_value=mock):
        result = await search_docs(query="test")

    assert len(result) == 2
    frameworks = {h["framework"] for h in result}
    assert frameworks == {"spark", "delta"}


@pytest.mark.anyio
async def test_mcp_search_docs_qdrant_error() -> None:
    """search_docs raises RuntimeError on QdrantError."""
    from app.server import search_docs
    from docs_shared.exceptions import QdrantError

    mock = MagicMock()
    mock.search = MagicMock(side_effect=QdrantError("Collection not found"))
    with patch("app.server.get_retriever", return_value=mock):
        with pytest.raises(RuntimeError, match="Qdrant error"):
            await search_docs(query="test")


# ---------------------------------------------------------------------------
# get_document
# ---------------------------------------------------------------------------


def test_mcp_get_document() -> None:
    """get_document returns full document content."""
    from app.server import get_document

    expected = "# Title\n\nDocument body."

    mock = MagicMock()
    mock.get_document = MagicMock(return_value=expected)
    with patch("app.server.get_retriever", return_value=mock):
        result = get_document(framework="spark", path="docs/sql.md")

    assert result == expected


def test_mcp_get_document_not_found() -> None:
    """get_document raises RuntimeError for missing documents."""
    from app.server import get_document

    mock = MagicMock()
    mock.get_document = MagicMock(side_effect=DocumentNotFoundError("Not found"))
    with patch("app.server.get_retriever", return_value=mock):
        with pytest.raises(RuntimeError, match="Document not found"):
            get_document(framework="spark", path="missing.md")


# ---------------------------------------------------------------------------
# list_sources
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_mcp_list_sources() -> None:
    """list_sources returns framework dict."""
    from app.server import list_sources

    expected = {
        "spark": ["docs/sql.md", "docs/streaming.md"],
        "delta": ["docs/intro.md"],
    }

    mock = MagicMock()
    mock.list_sources = AsyncMock(return_value=expected)
    with patch("app.server.get_retriever", return_value=mock):
        result = await list_sources()

    assert result == expected


@pytest.mark.anyio
async def test_mcp_list_sources_qdrant_error() -> None:
    """list_sources raises RuntimeError on QdrantError."""
    from app.server import list_sources

    mock = MagicMock()
    mock.list_sources = AsyncMock(side_effect=QdrantError("Connection failed"))
    with patch("app.server.get_retriever", return_value=mock):
        with pytest.raises(RuntimeError, match="Qdrant error"):
            await list_sources()
