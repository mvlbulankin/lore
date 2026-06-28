from __future__ import annotations
import pickle
from pathlib import Path
from rank_bm25 import BM25Okapi
from docs_shared.config import settings

def tokenize(text: str) -> list[str]:
    return [t.lower() for t in text.split() if t.strip()]

def build(chunks: list) -> None:
    corpus = [c.content for c in chunks]
    tokenized = [tokenize(c) for c in corpus]
    bm25 = BM25Okapi(tokenized)
    data = {
        "bm25": bm25,
        "ids": [f"{c.framework}/{c.source_path}/{c.chunk_index}" for c in chunks],
        "meta": [
            {
                "framework": c.framework,
                "source_path": c.source_path,
                "title": c.title,
                "heading": c.heading,
                "chunk_index": c.chunk_index,
                "content": c.content,
            }
            for c in chunks
        ],
    }
    Path(settings.bm25_path).write_bytes(pickle.dumps(data))
