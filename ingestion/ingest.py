from __future__ import annotations
import argparse
from pathlib import Path
import structlog
import chromadb

from docs_shared.config import settings
from docs_shared.guards import warn_if_embedding_drift
from chunker import make_chunks
from embedder import embed_batch
import bm25_index

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
    files = discover_files(data_dir, args.framework)
    log.info("files_discovered", count=len(files))

    chunks: list = []
    for fw, rel in files:
        text = (data_dir / fw / rel).read_text(encoding="utf-8")
        chunks.extend(make_chunks(fw, rel, text, settings.chunk_max_words, settings.chunk_overlap_words))
    log.info("chunks_created", count=len(chunks))

    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    coll = client.get_or_create_collection(
        name=settings.chroma_collection,
        embedding_function=None,
        metadata={"hnsw:space": "cosine", "embedding_model": settings.embedding_model},
    )
    warn_if_embedding_drift(coll.metadata)

    if args.clear:
        existing = coll.get(include=[])["ids"]
        if existing:
            coll.delete(ids=existing)
        log.info("collection_cleared")

    if chunks:
        texts = [c.content for c in chunks]
        embeddings = embed_batch(texts)
        ids = [f"{c.framework}/{c.source_path}/{c.chunk_index}" for c in chunks]
        metadatas = [
            {
                "framework": c.framework,
                "source_path": c.source_path,
                "title": c.title,
                "heading": c.heading,
                "chunk_index": c.chunk_index,
                "is_last_chunk": c.is_last_chunk,
                "has_code": c.has_code,
                "code_languages": ",".join(c.code_languages),
                "block_types": ",".join(c.block_types),
            }
            for c in chunks
        ]
        coll.upsert(ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)
        log.info("chroma_upserted", count=len(chunks))

    if chunks:
        if args.framework:
            all_files = discover_files(data_dir, None)
            all_chunks: list = []
            for fw, rel in all_files:
                text = (data_dir / fw / rel).read_text(encoding="utf-8")
                all_chunks.extend(make_chunks(fw, rel, text))
            bm25_index.build(all_chunks)
            log.info("bm25_built", count=len(all_chunks))
        else:
            bm25_index.build(chunks)
            log.info("bm25_built", count=len(chunks))

if __name__ == "__main__":
    main()