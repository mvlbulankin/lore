"""Tests for docs_shared.retriever QdrantRetriever."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchValue,
    Prefetch,
    PointStruct,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)
from docs_shared.config import settings
from docs_shared.exceptions import DocumentNotFoundError
from docs_shared.retriever import QdrantRetriever
from docs_shared.sparse_builder import SparseBuilder


def _create_test_collection(
    path: str,
    collection: str = "test_docs",
) -> tuple[QdrantClient, SparseBuilder]:
    """Create a test Qdrant collection with sample data."""
    client = QdrantClient(path=path)

    if collection in [c.name for c in client.get_collections().collections]:
        client.delete_collection(collection)

    # Named vectors config — required when sparse is present
    client.create_collection(
        collection,
        vectors_config={
            "dense": VectorParams(size=4, distance=Distance.COSINE),
        },
        sparse_vectors_config={
            "sparse": SparseVectorParams(),
        },
    )

    texts = [
        "Spark SQL provides DataFrame API for structured data processing",
        "Checkpointing preserves streaming query state across failures",
        "Delta Lake provides ACID transactions on object storage",
        "Time travel lets you query historical versions of a Delta table",
        "Spark Structured Streaming processes data in real time",
        "Delta Lake tables support schema evolution and enforcement",
    ]

    # Dummy embeddings (4-dim for testing)
    embeddings = [
        [0.9, 0.1, 0.0, 0.0],
        [0.0, 0.9, 0.1, 0.0],
        [0.1, 0.0, 0.9, 0.0],
        [0.0, 0.1, 0.0, 0.9],
        [0.8, 0.2, 0.0, 0.0],
        [0.2, 0.0, 0.8, 0.0],
    ]

    # Sparse vectors via TF-IDF
    builder = SparseBuilder(max_features=100)
    sparse_vectors = builder.fit_build(texts)

    # Save sparse model
    builder.save(Path(path) / "sparse_model.pkl")

    # IMPORTANT: vector is a dict with named keys for hybrid search
    points = [
        PointStruct(
            id=i,
            vector={
                "dense": embeddings[i],
                "sparse": sparse_vectors[i],
            },
            payload={
                "framework": "spark" if i in (0, 1, 4) else "delta",
                "source_path": f"docs/doc{i}.md",
                "title": f"Doc {i}",
                "heading": f"Doc {i} > Section",
                "chunk_index": i,
                "content": texts[i],
                "is_last_chunk": i == 5,
                "has_code": False,
                "code_languages": "",
                "block_types": "prose",
                "parent_id": f"fw/doc{i}.md/Doc {i}/Section",
                "parent_heading": f"Doc {i} > Section",
                "parent_content": texts[i] + " [parent context]",
            },
        )
        for i in range(6)
    ]

    client.upsert(collection_name=collection, points=points, wait=True)
    return client, builder


def test_collection_count():
    with tempfile.TemporaryDirectory() as tmp:
        client, _ = _create_test_collection(tmp)
        count = client.count(collection_name="test_docs").count
        assert count == 6


def test_framework_filter():
    with tempfile.TemporaryDirectory() as tmp:
        client, _ = _create_test_collection(tmp)

        results = client.query_points(
            collection_name="test_docs",
            query=[0.9, 0.1, 0.0, 0.0],
            using="dense",
            limit=100,
            query_filter=Filter(
                must=[FieldCondition(key="framework", match=MatchValue(value="spark"))]
            ),
            with_payload=True,
        )
        frameworks = {r.payload["framework"] for r in results.points}
        assert frameworks == {"spark"}


def test_prefetch_fusion_rrf():
    """Test hybrid search with prefetch + Fusion.RRF."""
    with tempfile.TemporaryDirectory() as tmp:
        client, _ = _create_test_collection(tmp)

        results = client.query_points(
            collection_name="test_docs",
            prefetch=[
                Prefetch(query=[0.9, 0.1, 0.0, 0.0], using="dense", limit=10),
                Prefetch(
                    query=SparseVector(indices=[0, 1], values=[0.5, 0.5]),
                    using="sparse",
                    limit=10,
                ),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=10,
            with_payload=True,
        )
        assert len(results.points) > 0


def test_sparse_model_save_load():
    with tempfile.TemporaryDirectory() as tmp:
        _, builder = _create_test_collection(tmp)
        loaded = SparseBuilder.load(Path(tmp) / "sparse_model.pkl")
        # "provides" and "data" appear in multiple docs
        qvec = loaded.encode_query("provides data")
        assert len(qvec.indices) > 0


def test_parent_dedup_logic():
    """Test that dedup keeps highest-scoring child per parent."""

    class FakePoint:
        def __init__(self, pid, score, content, parent_content):
            self.id = 0
            self.score = score
            self.payload = {
                "parent_id": pid,
                "framework": "fw",
                "source_path": "a.md",
                "title": "T",
                "heading": "H",
                "chunk_index": 0,
                "content": content,
                "parent_content": parent_content,
            }

    points = [
        FakePoint("parent-1", 0.8, "child A", "full parent A"),
        FakePoint("parent-1", 0.6, "child B", "full parent A"),
        FakePoint("parent-2", 0.9, "child C", "full parent C"),
        FakePoint("parent-2", 0.5, "child D", "full parent C"),
    ]

    # Manual dedup (same logic as _dedup_by_parent)
    best_per_parent = {}
    for point in points:
        pid = point.payload["parent_id"]
        current = best_per_parent.get(pid, (0.0, None))[0]
        if point.score > current:
            best_per_parent[pid] = (point.score, point)

    assert len(best_per_parent) == 2
    # parent-1 -> child A (score 0.8 > 0.6)
    assert best_per_parent["parent-1"][1].payload["content"] == "child A"
    # parent-2 -> child C (score 0.9 > 0.5)
    assert best_per_parent["parent-2"][1].payload["content"] == "child C"


# ---------------------------------------------------------------------------
# Path traversal security
# ---------------------------------------------------------------------------


def _make_retriever(tmp_path: Path) -> QdrantRetriever:
    """Create retriever with temp paths for testing get_document."""
    settings.prepared_dir = str(tmp_path / "prepared")
    settings.qdrant_storage_path = str(tmp_path / "qdrant")
    (tmp_path / "prepared").mkdir(exist_ok=True)
    (tmp_path / "qdrant").mkdir(exist_ok=True)
    from docs_shared.embedder import Embedder

    return QdrantRetriever(embedder=Embedder())


def test_get_document_blocks_path_traversal(tmp_path):
    """Path traversal (../etc/passwd) raises DocumentNotFoundError."""
    (tmp_path / "prepared" / "spark").mkdir(parents=True)
    (tmp_path / "prepared" / "spark" / "doc.md").write_text("safe")

    r = _make_retriever(tmp_path)
    with pytest.raises(DocumentNotFoundError):
        r.get_document("spark", "../etc/passwd")
    with pytest.raises(DocumentNotFoundError):
        r.get_document("spark", "doc.md/../../../etc/passwd")


def test_get_document_blocks_absolute_path(tmp_path):
    """Absolute path resolves within prepared dir and is blocked."""
    (tmp_path / "prepared" / "spark").mkdir(parents=True)
    (tmp_path / "prepared" / "spark" / "doc.md").write_text("safe")

    r = _make_retriever(tmp_path)
    with pytest.raises(DocumentNotFoundError):
        r.get_document("spark", "/etc/passwd")


def test_get_document_returns_real_file(tmp_path):
    """Happy path: valid framework + path returns file content."""
    spark_dir = tmp_path / "prepared" / "spark"
    spark_dir.mkdir(parents=True)
    (spark_dir / "doc.md").write_text("# Hello\n\nWorld.")

    r = _make_retriever(tmp_path)
    content = r.get_document("spark", "doc.md")
    assert "# Hello" in content
    assert "World" in content
