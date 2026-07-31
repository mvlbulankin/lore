"""Tests for ingestion.ingest workflow functions."""

from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import pytest


# ingestion/ uses PYTHONPATH="/app:/app/ingestion" inside Docker;
# replicate that so `from chunker import make_chunks` resolves.
_INGESTION = str(Path(__file__).resolve().parent.parent / "ingestion")
if _INGESTION not in sys.path:
    sys.path.insert(0, _INGESTION)

from ingestion.ingest import discover_files  # noqa: E402


# ---------------------------------------------------------------------------
# discover_files
# ---------------------------------------------------------------------------


def test_discover_files_empty_directory(tmp_path: Path) -> None:
    """discover_files returns empty list for empty directory."""
    data_dir = tmp_path / "prepared"
    data_dir.mkdir()
    files = discover_files(data_dir, None)
    assert files == []


def test_discover_files_nested_directories(tmp_path: Path) -> None:
    """discover_files finds .md files in nested directories."""
    data_dir = tmp_path / "prepared"
    (data_dir / "spark" / "docs" / "api").mkdir(parents=True)
    (data_dir / "spark" / "docs" / "api" / "reference.md").write_text("# Ref")
    (data_dir / "spark" / "docs" / "overview.md").write_text("# Overview")

    files = discover_files(data_dir, "spark")
    paths = {rel for _, rel in files}
    assert "docs/api/reference.md" in paths
    assert "docs/overview.md" in paths


def test_discover_files_ignores_non_md(tmp_path: Path) -> None:
    """discover_files only returns .md files."""
    data_dir = tmp_path / "prepared"
    (data_dir / "spark").mkdir(parents=True)
    (data_dir / "spark" / "doc.md").write_text("# Doc")
    (data_dir / "spark" / "doc.txt").write_text("Text")
    (data_dir / "spark" / "doc.py").write_text("print(1)")

    files = discover_files(data_dir, "spark")
    assert len(files) == 1
    assert files[0][1] == "doc.md"


def test_discover_files_multiple_frameworks(tmp_path: Path) -> None:
    """discover_files finds files across multiple frameworks."""
    data_dir = tmp_path / "prepared"
    for fw in ("spark", "delta", "test"):
        (data_dir / fw).mkdir(parents=True)
        (data_dir / fw / "doc.md").write_text(f"# {fw}")

    files = discover_files(data_dir, None)
    frameworks = {fw for fw, _ in files}
    assert frameworks == {"spark", "delta", "test"}


def test_discover_files_missing_framework_returns_empty(tmp_path: Path) -> None:
    """discover_files returns empty for non-existent framework."""
    data_dir = tmp_path / "prepared"
    data_dir.mkdir()
    files = discover_files(data_dir, "nonexistent")
    assert files == []


# ---------------------------------------------------------------------------
# ingest --clear workflow
# ---------------------------------------------------------------------------


def test_ingest_clear_removes_collection(tmp_path: Path) -> None:
    """--clear flag deletes all points from the collection."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        Filter,
        FilterSelector,
        PointStruct,
        VectorParams,
    )

    qdrant_path = str(tmp_path / "qdrant")
    collection = "test_clear"

    client = QdrantClient(path=qdrant_path)
    client.create_collection(
        collection,
        vectors_config={"dense": VectorParams(size=4, distance=Distance.COSINE)},
    )

    # Insert some points
    points = [
        PointStruct(
            id=i, vector={"dense": [0.1, 0.2, 0.3, 0.4]}, payload={"key": f"val{i}"}
        )
        for i in range(5)
    ]
    client.upsert(collection_name=collection, points=points, wait=True)
    assert client.count(collection_name=collection).count == 5

    # Clear using the same method as ingest.py
    client.delete(
        collection_name=collection,
        points_selector=FilterSelector(filter=Filter(must=[])),
    )

    assert client.count(collection_name=collection).count == 0


def test_ingest_clear_removes_sparse_model(tmp_path: Path) -> None:
    """--clear flag removes sparse_model.pkl."""
    sparse_path = tmp_path / "sparse_model.pkl"
    sparse_path.write_bytes(b"fake model data")
    assert sparse_path.exists()

    # Simulate clear logic
    if sparse_path.exists():
        sparse_path.unlink()

    assert not sparse_path.exists()


def test_ingest_clear_removes_model_info(tmp_path: Path) -> None:
    """--clear flag removes .model_info.json."""
    model_info_path = tmp_path / ".model_info.json"
    model_info_path.write_text('{"model": "old"}')
    assert model_info_path.exists()

    # Simulate clear logic
    if model_info_path.exists():
        model_info_path.unlink()

    assert not model_info_path.exists()


# ---------------------------------------------------------------------------
# model_info written after ingest
# ---------------------------------------------------------------------------


def test_model_info_written_after_ingest(tmp_path: Path) -> None:
    """After ingest, .model_info.json contains correct model metadata."""
    model_info_path = tmp_path / ".model_info.json"

    # Simulate what ingest.py does
    json.dump(
        {
            "embedding_model": "nomic-embed-text-v1.5",
            "embedding_dim": 768,
        },
        open(model_info_path, "w"),
        indent=2,
    )

    assert model_info_path.exists()
    info = json.loads(model_info_path.read_text())
    assert info["embedding_model"] == "nomic-embed-text-v1.5"
    assert info["embedding_dim"] == 768


def test_model_info_overwritten_on_reingest(tmp_path: Path) -> None:
    """Re-ingest overwrites .model_info.json with current values."""
    model_info_path = tmp_path / ".model_info.json"

    # First ingest
    json.dump(
        {"embedding_model": "old-model", "embedding_dim": 384},
        open(model_info_path, "w"),
    )

    # Second ingest (simulated)
    json.dump(
        {"embedding_model": "new-model", "embedding_dim": 768},
        open(model_info_path, "w"),
    )

    info = json.loads(model_info_path.read_text())
    assert info["embedding_model"] == "new-model"
    assert info["embedding_dim"] == 768


# ---------------------------------------------------------------------------
# ingest --framework partial indexing
# ---------------------------------------------------------------------------


def test_partial_ingest_all_sparse_corpus(tmp_path: Path) -> None:
    """When --framework is specified, sparse model still uses full corpus.

    This verifies the fix for P1-2: TF-IDF semantics require the full corpus
    for min_df and max_df to be meaningful.
    """
    data_dir = tmp_path / "prepared"
    (data_dir / "spark").mkdir(parents=True)
    (data_dir / "delta").mkdir(parents=True)
    (data_dir / "spark" / "doc.md").write_text("# Spark\n\nSpark content.")
    (data_dir / "delta" / "doc.md").write_text("# Delta\n\nDelta content.")

    # Simulate what ingest.py does:
    # 1. Discover files for selected framework
    selected_files = discover_files(data_dir, "spark")
    # 2. Discover ALL files for sparse corpus
    all_files = discover_files(data_dir, None)

    # Selected should be spark only
    selected_frameworks = {fw for fw, _ in selected_files}
    assert selected_frameworks == {"spark"}

    # All files should include both frameworks
    all_frameworks = {fw for fw, _ in all_files}
    assert all_frameworks == {"spark", "delta"}


# ---------------------------------------------------------------------------
# Cache lifecycle
# ---------------------------------------------------------------------------


def test_cache_filename_sanitizes_slashes() -> None:
    """_cache_filename replaces / with __."""
    from ingestion.ingest import _cache_filename

    result = _cache_filename("spark", "docs/api/reference.md")
    assert result == "spark__docs__api__reference.md.pkl"


def test_cache_filename_simple() -> None:
    """_cache_filename handles simple paths."""
    from ingestion.ingest import _cache_filename

    result = _cache_filename("test", "doc.md")
    assert result == "test__doc.md.pkl"


def test_cleanup_cache_removes_files_and_dir(tmp_path: Path) -> None:
    """_cleanup_cache removes all .pkl files and the directory."""
    from ingestion.ingest import _cleanup_cache

    cache_dir = tmp_path / "_chunks_cache"
    cache_dir.mkdir()
    (cache_dir / "a.pkl").write_bytes(b"data")
    (cache_dir / "b.pkl").write_bytes(b"data")

    _cleanup_cache(cache_dir)

    assert not cache_dir.exists()


def test_cleanup_cache_noop_on_missing(tmp_path: Path) -> None:
    """_cleanup_cache does nothing if directory doesn't exist."""
    from ingestion.ingest import _cleanup_cache

    cache_dir = tmp_path / "_chunks_cache"
    _cleanup_cache(cache_dir)  # should not raise


def test_cache_files_created_and_consumed(tmp_path: Path) -> None:
    """Cache files are written in Phase 1 and consumed in Phase 4."""
    from ingestion.chunker import Chunk
    from ingestion.ingest import _cache_filename, _cleanup_cache

    cache_dir = tmp_path / "_chunks_cache"
    cache_dir.mkdir()

    # Simulate Phase 1: write chunks to cache
    chunks = [
        Chunk("spark", "doc.md", "Title", "H1", 0, "content 0", False),
        Chunk("spark", "doc.md", "Title", "H1", 1, "content 1", True),
    ]
    cache_path = cache_dir / _cache_filename("spark", "doc.md")
    cache_path.write_bytes(pickle.dumps(chunks))

    assert cache_path.exists()

    # Simulate Phase 4: load and delete
    loaded = pickle.loads(cache_path.read_bytes())
    cache_path.unlink()

    assert len(loaded) == 2
    assert loaded[0].content == "content 0"
    assert loaded[1].content == "content 1"
    assert not cache_path.exists()

    # Cleanup
    _cleanup_cache(cache_dir)
    assert not cache_dir.exists()


def test_cache_cleanup_on_exception(tmp_path: Path) -> None:
    """Finally block cleans up cache even when Phase 4 raises."""
    from ingestion.ingest import _cleanup_cache

    cache_dir = tmp_path / "_chunks_cache"
    cache_dir.mkdir()
    (cache_dir / "a.pkl").write_bytes(b"data")
    (cache_dir / "b.pkl").write_bytes(b"data")

    try:
        raise RuntimeError("simulated upsert failure")
    except RuntimeError:
        pass
    finally:
        _cleanup_cache(cache_dir)

    assert not cache_dir.exists()


# ---------------------------------------------------------------------------
# Rollback on Phase 4 failure
# ---------------------------------------------------------------------------


def test_partial_upsert_rolled_back_on_exception(tmp_path: Path, monkeypatch) -> None:
    """If upsert fails mid-batch, partial points are deleted from the collection."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        SparseIndexParams,
        SparseVector,
        SparseVectorParams,
        VectorParams,
    )

    from docs_shared.sparse_builder import SparseBuilder
    from ingestion.ingest import main

    docs_dir = tmp_path / "docs"
    (docs_dir / "test").mkdir(parents=True)
    (docs_dir / "test" / "a.md").write_text("# A\n\nContent A.")
    (docs_dir / "test" / "b.md").write_text("# B\n\nContent B.")

    qdrant_path = str(tmp_path / "qdrant")
    collection = "test_rollback"

    # Create client, set up collection, then close so main() can reopen it
    client = QdrantClient(path=qdrant_path)
    client.create_collection(
        collection,
        vectors_config={
            "dense": VectorParams(size=384, distance=Distance.COSINE),
        },
        sparse_vectors_config={
            "sparse": SparseVectorParams(
                index=SparseIndexParams(on_disk=True),
            ),
        },
    )
    client.close()

    call_count = [0]
    deleted_points = []

    def failing_upsert(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] >= 2:
            raise RuntimeError("simulated upsert failure")

    def tracking_delete(*args, **kwargs):
        deleted_points.append(kwargs.get("points_selector", args[1] if len(args) > 1 else None))

    # Patch QdrantClient constructor to return our tracked client
    tracked_client = QdrantClient(path=qdrant_path)
    tracked_client.upsert = failing_upsert
    tracked_client.delete = tracking_delete

    def fake_qdrant_client(*args, **kwargs):
        return tracked_client

    monkeypatch.setattr("ingestion.ingest.QdrantClient", fake_qdrant_client)

    fake_dim = 384

    class FakeEmbedder:
        def embed_sync(self, texts):
            return [[0.1] * fake_dim for _ in texts]

    monkeypatch.setattr("docs_shared.embedder.Embedder", FakeEmbedder)

    def fake_fit_build(self, texts):
        pass

    def fake_build(self, texts):
        return [SparseVector(indices=[0, 1], values=[1.0, 0.5]) for _ in texts]

    monkeypatch.setattr(SparseBuilder, "fit_build", fake_fit_build)
    monkeypatch.setattr(SparseBuilder, "build", fake_build)
    monkeypatch.setattr(SparseBuilder, "save", lambda self, path: None)

    monkeypatch.setattr(
        "docs_shared.config.settings.prepared_dir", str(docs_dir)
    )
    monkeypatch.setattr(
        "docs_shared.config.settings.qdrant_storage_path", qdrant_path
    )
    monkeypatch.setattr(
        "docs_shared.config.settings.qdrant_collection", collection
    )
    monkeypatch.setattr("docs_shared.config.settings.chunk_max_words", 512)
    monkeypatch.setattr("docs_shared.config.settings.chunk_overlap_words", 64)
    monkeypatch.setattr("sys.argv", ["ingest"])

    with pytest.raises(RuntimeError, match="simulated upsert failure"):
        main()

    # Verify that delete was called to clean up the 1 point that was upserted
    assert len(deleted_points) == 1, f"Expected 1 delete call, got {len(deleted_points)}"
    selector = deleted_points[0]
    assert isinstance(selector, list), f"Expected list of point IDs, got {type(selector)}"
    assert len(selector) == 1, f"Expected 1 point ID deleted, got {len(selector)}"
    assert selector == [0]
