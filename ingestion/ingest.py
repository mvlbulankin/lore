from __future__ import annotations

import argparse
import gc
import json
import pickle
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
from docs_shared.embedder import Embedder
from docs_shared.logging import configure_logging
from ingestion.chunker import Chunk, make_chunks
from docs_shared.sparse_builder import SparseBuilder

configure_logging()
log = structlog.get_logger()


def _cache_filename(fw: str, rel: str) -> str:
    return f"{fw}__{rel.replace('/', '__')}.pkl"


def _cleanup_cache(cache_dir: Path) -> None:
    if not cache_dir.exists():
        return
    try:
        for p in cache_dir.glob("*.pkl"):
            p.unlink(missing_ok=True)
        cache_dir.rmdir()
    except OSError:
        pass


def discover_files(data_dir: Path, framework: str | None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    fws = (
        [framework] if framework else [p.name for p in data_dir.iterdir() if p.is_dir()]
    )
    for fw in fws:
        fw_dir = data_dir / fw
        if not fw_dir.exists():
            continue
        for p in fw_dir.rglob("*.md"):
            rel = p.relative_to(fw_dir).as_posix()
            out.append((fw, rel))
    return out


def _chunk_file(data_dir: Path, fw: str, rel: str) -> list:
    text = (data_dir / fw / rel).read_text(encoding="utf-8")
    return make_chunks(
        fw,
        rel,
        text,
        settings.chunk_max_words,
        settings.chunk_overlap_words,
        settings.parent_level,
    )


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

    all_files = discover_files(data_dir, None)

    # Phase 1: chunk everything, stream to pickle cache, collect texts for TF-IDF
    chunks_cache_dir = Path(qdrant_path) / "_chunks_cache"
    chunks_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_files: dict[tuple[str, str], Path] = {}
    all_texts: list[str] = []
    total_chunks = 0
    for fw, rel in all_files:
        chunks = _chunk_file(data_dir, fw, rel)
        cache_path = chunks_cache_dir / _cache_filename(fw, rel)
        cache_path.write_bytes(pickle.dumps(chunks))
        cache_files[(fw, rel)] = cache_path
        for c in chunks:
            all_texts.append(c.content)
        total_chunks += len(chunks)
        del chunks
    log.info("chunks_created", count=total_chunks)

    # Phase 2: build TF-IDF model
    sparse_builder = SparseBuilder()
    sparse_builder.fit_build(all_texts)
    log.info("sparse_model_fitted", corpus_docs=len(all_texts))

    # Free texts
    del all_texts
    gc.collect()

    # Phase 3: initialize Qdrant
    client = QdrantClient(path=qdrant_path)
    sparse_path = Path(qdrant_path) / "sparse_model.pkl"

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

    if args.clear:
        client.delete(
            collection_name=collection,
            points_selector=FilterSelector(filter=Filter(must=[])),
        )
        if sparse_path.exists():
            sparse_path.unlink()
        model_info_path = Path(qdrant_path) / ".model_info.json"
        if model_info_path.exists():
            model_info_path.unlink()
        log.info("collection_cleared")

    # Save sparse model (single write after potential clear)
    sparse_builder.save(sparse_path)

    # Initialize single embedder for entire run
    embedder = Embedder(model_name=settings.embedding_model)
    log.info("embedder_initialized", model=settings.embedding_model)

    try:
        # Phase 4: process one document at a time
        point_id = 0
        total_upserted = 0

        for fw, rel in files:
            cache_path = cache_files.pop((fw, rel))
            chunks: list[Chunk] = pickle.loads(cache_path.read_bytes())
            cache_path.unlink(missing_ok=True)

            if not chunks:
                continue

            log.info("processing_file", framework=fw, file=rel, chunks=len(chunks))

            for chunk in chunks:
                dense_vec = embedder.embed_sync([chunk.content])[0]
                sparse_vec = sparse_builder.build([chunk.content])[0]

                point = PointStruct(
                    id=point_id,
                    vector={
                        "dense": dense_vec,
                        "sparse": sparse_vec,
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
                client.upsert(collection_name=collection, points=[point], wait=True)
                point_id += 1
                total_upserted += 1

            del chunks
            log.info("file_done", framework=fw, file=rel)

        del sparse_builder

        log.info("qdrant_upserted", count=total_upserted)

        # Save embedding model metadata for drift detection
        model_info_path = Path(qdrant_path) / ".model_info.json"
        with open(model_info_path, "w") as f:
            json.dump(
                {
                    "embedding_model": settings.embedding_model,
                    "embedding_dim": settings.embedding_dim,
                },
                f,
                indent=2,
            )
    finally:
        del embedder
        client.close()
        _cleanup_cache(chunks_cache_dir)
        gc.collect()


if __name__ == "__main__":
    main()
