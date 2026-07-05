"""End-to-end integration test: prepare -> ingest -> search."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ingestion/ uses PYTHONPATH="/app:/app/ingestion" inside Docker;
# replicate that so `from chunker import make_chunks` resolves.
_INGESTION = str(Path(__file__).resolve().parent.parent / "ingestion")
if _INGESTION not in sys.path:
    sys.path.insert(0, _INGESTION)

from docs_shared.config import Settings  # noqa: E402
from docs_shared.retriever import QdrantRetriever  # noqa: E402
from ingestion.chunker import make_chunks  # noqa: E402
from ingestion.ingest import discover_files  # noqa: E402
from docs_shared.sparse_builder import SparseBuilder  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_env(tmp_path: Path) -> dict[str, str]:
    """Create a temporary environment with prepared docs and Qdrant storage."""
    prepared_dir = tmp_path / "prepared"
    spark_dir = prepared_dir / "spark" / "docs"
    spark_dir.mkdir(parents=True)

    (spark_dir / "sql.md").write_text(
        "# Spark SQL\n\n"
        "## DataFrame API\n\n"
        "Spark SQL provides a DataFrame API that allows structured data processing.\n\n"
        "## SQL Queries\n\n"
        "You can also write SQL queries directly using the spark.sql method.\n",
        encoding="utf-8",
    )
    (spark_dir / "streaming.md").write_text(
        "# Structured Streaming\n\n"
        "## Overview\n\n"
        "Structured Streaming is a scalable and fault-tolerant stream processing engine.\n\n"
        "## Checkpointing\n\n"
        "Checkpointing preserves streaming query state across failures.\n",
        encoding="utf-8",
    )

    delta_dir = prepared_dir / "delta" / "docs"
    delta_dir.mkdir(parents=True)
    (delta_dir / "intro.md").write_text(
        "# Delta Lake\n\n"
        "## ACID Transactions\n\n"
        "Delta Lake provides ACID transactions on object storage.\n\n"
        "## Time Travel\n\n"
        "Time travel lets you query historical versions of a Delta table.\n",
        encoding="utf-8",
    )

    qdrant_path = str(tmp_path / "qdrant")
    return {
        "prepared_dir": str(prepared_dir),
        "qdrant_path": qdrant_path,
    }


def _make_settings(prepared_dir: str, qdrant_path: str) -> Settings:
    return Settings(
        embedding_model="test-model",
        embedding_dim=16,
        qdrant_storage_path=qdrant_path,
        qdrant_collection="test_docs",
        prepared_dir=prepared_dir,
        server_port=8000,
        chunk_max_words=800,
        chunk_overlap_words=80,
        parent_level=2,
    )


def _ingest_test_corpus(
    prepared_dir: Path,
    qdrant_path: str,
    collection: str = "test_docs",
    embedding_dim: int = 16,
) -> None:
    """Ingest test documents into a Qdrant instance with mock embeddings.

    Creates collection, chunks documents, builds dummy dense + sparse
    vectors, and upserts.  This helper is shared by all ingest-based tests
    to avoid duplicating the setup logic.
    """
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        PointStruct,
        SparseIndexParams,
        SparseVectorParams,
        VectorParams,
    )

    files = discover_files(prepared_dir, None)
    chunks = []
    for fw, rel in files:
        text = (prepared_dir / fw / rel).read_text(encoding="utf-8")
        chunks.extend(make_chunks(fw, rel, text))

    embeddings = [[0.1] * embedding_dim for _ in chunks]

    all_texts = [c.content for c in chunks]
    sparse_builder = SparseBuilder()
    sparse_vectors = sparse_builder.fit_build(all_texts)

    client = QdrantClient(path=qdrant_path)
    try:
        collections = [c.name for c in client.get_collections().collections]
        if collection not in collections:
            client.create_collection(
                collection,
                vectors_config={
                    "dense": VectorParams(size=embedding_dim, distance=Distance.COSINE),
                },
                sparse_vectors_config={
                    "sparse": SparseVectorParams(index=SparseIndexParams(on_disk=True)),
                },
            )

        points = []
        for i, chunk in enumerate(chunks):
            points.append(
                PointStruct(
                    id=i,
                    vector={"dense": embeddings[i], "sparse": sparse_vectors[i]},
                    payload={
                        "framework": chunk.framework,
                        "source_path": chunk.source_path,
                        "title": chunk.title,
                        "heading": chunk.heading,
                        "chunk_index": chunk.chunk_index,
                        "content": chunk.content,
                        "parent_id": chunk.parent_id or "",
                        "parent_content": chunk.parent_content or "",
                    },
                )
            )

        client.upsert(collection_name=collection, points=points, wait=True)
    finally:
        client.close()

    # Save artifacts needed by tests
    sparse_builder.save(Path(qdrant_path) / "sparse_model.pkl")
    model_info = {"embedding_model": "test-model", "embedding_dim": embedding_dim}
    json.dump(model_info, open(Path(qdrant_path) / ".model_info.json", "w"), indent=2)


# ---------------------------------------------------------------------------
# discover_files
# ---------------------------------------------------------------------------


def test_discover_files_all_frameworks(test_env: dict[str, str]) -> None:
    """discover_files finds all .md files across frameworks."""
    files = discover_files(Path(test_env["prepared_dir"]), None)
    frameworks = {fw for fw, _ in files}
    assert frameworks == {"spark", "delta"}
    assert len(files) == 3


def test_discover_files_single_framework(test_env: dict[str, str]) -> None:
    """discover_files filters by framework."""
    files = discover_files(Path(test_env["prepared_dir"]), "spark")
    frameworks = {fw for fw, _ in files}
    assert frameworks == {"spark"}
    assert len(files) == 2


def test_discover_files_missing_framework(test_env: dict[str, str]) -> None:
    """discover_files returns empty for missing framework."""
    files = discover_files(Path(test_env["prepared_dir"]), "nonexistent")
    assert files == []


# ---------------------------------------------------------------------------
# ingest workflow
# ---------------------------------------------------------------------------


def test_ingest_creates_model_info(test_env: dict[str, str]) -> None:
    """After ingest, .model_info.json is written with correct values."""
    prepared_dir = Path(test_env["prepared_dir"])
    qdrant_path = test_env["qdrant_path"]
    collection = "test_docs"

    _ingest_test_corpus(prepared_dir, qdrant_path, collection)

    model_info_path = Path(qdrant_path) / ".model_info.json"
    assert model_info_path.exists()
    info = json.loads(model_info_path.read_text())
    assert info["embedding_model"] == "test-model"
    assert info["embedding_dim"] == 16

    from qdrant_client import QdrantClient

    client = QdrantClient(path=qdrant_path)
    try:
        count = client.count(collection_name=collection).count
    finally:
        client.close()
    assert count > 0


# ---------------------------------------------------------------------------
# search end-to-end (mocked embedder)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_end_to_end(test_env: dict[str, str]) -> None:
    """Full pipeline: ingest -> search -> verify results."""
    prepared_dir = Path(test_env["prepared_dir"])
    qdrant_path = test_env["qdrant_path"]
    collection = "test_docs"

    _ingest_test_corpus(prepared_dir, qdrant_path, collection)

    # Search via QdrantRetriever (mock embedder)
    settings = _make_settings(str(prepared_dir), qdrant_path)

    with patch("docs_shared.retriever.settings", settings):
        mock_embedder = MagicMock()
        mock_embedder.embed_one = AsyncMock(return_value=[0.1] * 16)
        retriever = QdrantRetriever(embedder=mock_embedder)

        hits = await retriever.search("DataFrame API", framework="spark", limit=5)

        await retriever.aclose()

    assert len(hits) > 0
    assert all(h.framework == "spark" for h in hits)
    assert any("DataFrame" in h.heading or "DataFrame" in h.content for h in hits)


@pytest.mark.anyio
async def test_search_framework_isolation(test_env: dict[str, str]) -> None:
    """Framework filter isolates spark from delta results."""
    prepared_dir = Path(test_env["prepared_dir"])
    qdrant_path = test_env["qdrant_path"]
    collection = "test_docs"

    _ingest_test_corpus(prepared_dir, qdrant_path, collection)

    settings = _make_settings(str(prepared_dir), qdrant_path)

    with patch("docs_shared.retriever.settings", settings):
        mock_embedder = MagicMock()
        mock_embedder.embed_one = AsyncMock(return_value=[0.1] * 16)
        retriever = QdrantRetriever(embedder=mock_embedder)

        delta_hits = await retriever.search("ACID", framework="delta", limit=5)
        spark_hits = await retriever.search("ACID", framework="spark", limit=5)

        await retriever.aclose()

    assert all(h.framework == "delta" for h in delta_hits)
    assert all(h.framework == "spark" for h in spark_hits)
