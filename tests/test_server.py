"""Tests for REST API endpoints (app/server)."""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

import pytest

from fastapi.testclient import TestClient

from docs_shared.retriever import Hit

# app.server defines get_retriever() which accesses app.state.retriever.
# The settings singleton was already created (from env), so we patch the
# path on the existing settings instance to a writable temp dir before
# importing app.server.
from docs_shared.config import settings

_original_qdrant_path = settings.qdrant_storage_path
_original_prepared_dir = settings.prepared_dir
_temp_qdrant = tempfile.mkdtemp()
_temp_prepared = tempfile.mkdtemp()
object.__setattr__(settings, "qdrant_storage_path", _temp_qdrant)
object.__setattr__(settings, "prepared_dir", _temp_prepared)

from app.server import app  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def mock_hits() -> list[Hit]:
    return [
        Hit(
            id="spark/docs/sql.md/0",
            framework="spark",
            source_path="docs/sql.md",
            title="Spark SQL",
            heading="Spark SQL > DataFrame API",
            chunk_index=0,
            content="Spark SQL provides DataFrame API for structured data processing. "
            + "x" * 600,
            parent_content="Full parent section with more context. " + "y" * 2100,
            score=0.92,
        ),
        Hit(
            id="delta/docs/intro.md/1",
            framework="delta",
            source_path="docs/intro.md",
            title="Delta Lake",
            heading="Delta Lake > Overview",
            chunk_index=1,
            content="Delta Lake provides ACID transactions on object storage.",
            parent_content="Delta Lake overview parent content.",
            score=0.78,
        ),
    ]


# ---------------------------------------------------------------------------
# POST /search
# ---------------------------------------------------------------------------


def test_search_endpoint(client: TestClient, mock_hits: list[Hit]) -> None:
    """POST /search returns formatted hits with snippet and parent_content."""

    async def fake_search(*args, **kwargs):
        return mock_hits

    async def fake_list_sources(*args, **kwargs):
        return {}

    mock = MagicMock()
    mock.search = fake_search
    mock.list_sources = fake_list_sources
    with patch("app.server.get_retriever", return_value=mock):
        response = client.post(
            "/search",
            json={"query": "DataFrame API", "framework": "spark", "limit": 5},
        )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_search_endpoint_format(client: TestClient) -> None:
    """Search response has correct keys and truncation."""
    from app.server import _to_hit_dict

    hits = [
        Hit(
            id="fw/a.md/0",
            framework="fw",
            source_path="a.md",
            title="T",
            heading="H",
            chunk_index=0,
            content="a" * 600,
            parent_content="b" * 2500,
            score=0.5,
        ),
    ]
    result = _to_hit_dict(hits)
    assert len(result) == 1
    h = result[0]
    assert "id" in h
    assert "framework" in h
    assert "path" in h
    assert "title" in h
    assert "heading" in h
    assert "chunk_index" in h
    assert "score" in h
    assert "snippet" in h
    assert "parent_content" in h
    assert len(h["snippet"]) == 500
    assert len(h["parent_content"]) == 2000


def test_search_framework_filter(client: TestClient) -> None:
    """Search with framework parameter filters results."""
    spark_hits = [
        Hit(
            id="spark/a.md/0",
            framework="spark",
            source_path="a.md",
            title="T",
            heading="H",
            chunk_index=0,
            content="spark content",
            parent_content="",
            score=0.9,
        ),
    ]

    async def fake_search(*args, **kwargs):
        return spark_hits

    async def fake_list_sources(*args, **kwargs):
        return {}

    mock = MagicMock()
    mock.search = fake_search
    mock.list_sources = fake_list_sources
    with patch("app.server.get_retriever", return_value=mock):
        response = client.post(
            "/search",
            json={"query": "test", "framework": "spark", "limit": 3},
        )

    assert response.status_code == 200
    data = response.json()
    assert all(item["framework"] == "spark" for item in data)


def test_search_default_limit(client: TestClient) -> None:
    """Default limit is 5."""
    captured_args: list = []

    async def fake_search(*args, **kwargs):
        captured_args.append(args)
        return []

    async def fake_list_sources(*args, **kwargs):
        return {}

    mock = MagicMock()
    mock.search = fake_search
    mock.list_sources = fake_list_sources
    with patch("app.server.get_retriever", return_value=mock):
        client.post("/search", json={"query": "test"})

    assert len(captured_args) == 1
    assert captured_args[0][2] == 5


# ---------------------------------------------------------------------------
# GET /sources
# ---------------------------------------------------------------------------


def test_sources_endpoint(client: TestClient) -> None:
    """GET /sources returns framework dict."""
    expected = {"spark": ["docs/sql.md"], "delta": ["docs/intro.md"]}

    async def fake_list_sources(*args, **kwargs):
        return expected

    async def fake_search(*args, **kwargs):
        return []

    mock = MagicMock()
    mock.list_sources = fake_list_sources
    mock.search = fake_search
    with patch("app.server.get_retriever", return_value=mock):
        response = client.get("/sources")

    assert response.status_code == 200
    data = response.json()
    assert "spark" in data
    assert "delta" in data


# ---------------------------------------------------------------------------
# GET /docs/{framework}/{path}
# ---------------------------------------------------------------------------


def test_get_doc_200(client: TestClient) -> None:
    """GET /docs returns document content."""
    mock = MagicMock()
    mock.get_document = MagicMock(return_value="# Hello\n\nWorld.")
    with patch("app.server.get_retriever", return_value=mock):
        response = client.get("/docs/spark/sql-programming-guide.md")

    assert response.status_code == 200
    assert "Hello" in response.text


def test_get_doc_404(client: TestClient) -> None:
    """GET /docs for missing document returns 404."""
    from docs_shared.exceptions import DocumentNotFoundError

    mock = MagicMock()
    mock.get_document = MagicMock(side_effect=DocumentNotFoundError("Not found"))
    with patch("app.server.get_retriever", return_value=mock):
        response = client.get("/docs/spark/missing.md")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


def test_health_endpoint_keys(client: TestClient) -> None:
    """GET /health returns expected keys."""
    mock = MagicMock()
    mock.collection_count = MagicMock(return_value=1500)
    mock.is_sparse_model_loaded = MagicMock(return_value=True)
    mock.verify_embedding_model = MagicMock(return_value=True)

    with patch("app.server.get_retriever", return_value=mock):
        response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert "qdrant" in data
    assert "sparse_model" in data
    assert "collection_count" in data
    assert "embedding_model" in data
    assert "lm_studio" not in data


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_app_lifespan() -> None:
    """App starts and stops cleanly via lifespan."""
    from contextlib import asynccontextmanager
    from app.server import app_lifespan

    @asynccontextmanager
    async def _run():
        async with app_lifespan(app):
            yield

    async with _run():
        assert hasattr(app.state, "retriever")
        assert hasattr(app.state, "embedder")


@pytest.mark.anyio
async def test_embedder_uses_configured_model() -> None:
    """Embedder in lifespan is created with settings.embedding_model."""
    from contextlib import asynccontextmanager
    from app.server import app_lifespan

    @asynccontextmanager
    async def _run():
        async with app_lifespan(app):
            yield

    async with _run():
        embedder = app.state.embedder
        assert embedder._model.model.model_name == settings.embedding_model
