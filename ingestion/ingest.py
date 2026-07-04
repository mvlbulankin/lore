from __future__ import annotations
import argparse
from pathlib import Path
import structlog

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    Filter,
    FilterSelector,
    PointStruct,
    SparseIndexParams,
    SparseVectorParams,
    VectorParams,
)

from docs_shared.config import settings
from chunker import make_chunks
from embedder import embed_batch
from sparse_builder import SparseBuilder

log = structlog.get_logger()


def discover_files(data_dir: Path, framework: str | None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    fws = [framework] if framework else [p.name for p in data_dir.iterdir() if p.is_dir()]
    for fw in fws:
        fw_dir = data_dir / fw
        if not fw_dir.exists():
            continue
        for p in fw_dir.rglob("*.md"):
            rel = p.relative_to(fw_dir).as_posix()
            out.append((fw, rel))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--framework", default=None)
    parser.add_argument("--clear", action="store_true")
    args = parser.parse_args()

    data_dir = Path(settings.prepared_dir)
    qdrant_path = settings.qdrant_storage_path
    collection = settings.qdrant_collection

    files = discover_files(data_dir, args.framework)
    log.info("files_discovered", count=len(files))

    chunks: list = []
    for fw, rel in files:
        text = (data_dir / fw / rel).read_text(encoding="utf-8")
        chunks.extend(
            make_chunks(
                fw,
                rel,
                text,
                settings.chunk_max_words,
                settings.chunk_overlap_words,
                settings.parent_level,
            )
        )
    log.info("chunks_created", count=len(chunks))

    # Initialize Qdrant (embedded)
    client = QdrantClient(path=qdrant_path)

    # Create collection if needed
    collections = [c.name for c in client.get_collections().collections]
    if collection not in collections:
        client.create_collection(
            collection,
            vectors_config={
                "dense": VectorParams(
                    size=settings.embedding_dim,
                    distance=Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                "sparse": SparseVectorParams(
                    index=SparseIndexParams(on_disk=True),
                ),
            },
        )
        log.info("qdrant_collection_created", name=collection)

    # Clear if requested
    if args.clear:
        client.delete(
            collection_name=collection,
            points_selector=FilterSelector(filter=Filter()),
        )
        sparse_path = Path(qdrant_path) / "sparse_model.pkl"
        if sparse_path.exists():
            sparse_path.unlink()
        log.info("collection_cleared")

    if not chunks:
        log.info("no_chunks_to_index")
        return

    # Build embeddings (dense vectors)
    texts = [c.content for c in chunks]
    embeddings = embed_batch(texts)
    log.info("embeddings_built", count=len(embeddings))

    # Build sparse vectors (TF-IDF)
    sparse_builder = SparseBuilder()
    sparse_vectors = sparse_builder.fit_build(texts)
    log.info("sparse_vectors_built", count=len(sparse_vectors))

    # Save sparse model for query time
    sparse_path = Path(qdrant_path) / "sparse_model.pkl"
    sparse_builder.save(sparse_path)

    # Build points with parent-child payload
    points: list[PointStruct] = []
    for i, chunk in enumerate(chunks):
        point = PointStruct(
            id=i,
            vector={
                "dense": embeddings[i],
                "sparse": sparse_vectors[i],
            },
            payload={
                "framework": chunk.framework,
                "source_path": chunk.source_path,
                "title": chunk.title,
                "heading": chunk.heading,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "is_last_chunk": chunk.is_last_chunk,
                "has_code": chunk.has_code,
                "code_languages": ",".join(chunk.code_languages),
                "block_types": ",".join(chunk.block_types),
                "parent_id": chunk.parent_id or "",
                "parent_heading": chunk.parent_heading or "",
                "parent_content": chunk.parent_content or "",
            },
        )
        points.append(point)

    # Upsert in batches
    batch_size = 500
    for start in range(0, len(points), batch_size):
        batch = points[start:start + batch_size]
        client.upsert(collection_name=collection, points=batch, wait=True)

    log.info("qdrant_upserted", count=len(points))


if __name__ == "__main__":
    main()
