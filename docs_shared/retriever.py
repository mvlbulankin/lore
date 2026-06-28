from __future__ import annotations
import pickle
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
from rank_bm25 import BM25Okapi
import httpx
import structlog

from .config import settings

log = structlog.get_logger()

http_transport = httpx.HTTPTransport(retries=3)
http_client = httpx.Client(transport=http_transport, timeout=60.0)

@dataclass
class Hit:
    id: str
    framework: str
    source_path: str
    title: str
    heading: str
    chunk_index: int
    content: str
    score: float

class HybridRetriever:
    def __init__(self) -> None:
        self.client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        self.coll = self.client.get_or_create_collection(
            name=settings.chroma_collection,
            embedding_function=None,
            metadata={"hnsw:space": "cosine", "embedding_model": settings.embedding_model},
        )
        self.bm25: BM25Okapi | None = None
        self.bm25_ids: list[str] = []
        self.bm25_meta: list[dict[str, Any]] = []
        self._load_bm25()

    def _load_bm25(self) -> None:
        p = Path(settings.bm25_path)
        if not p.exists():
            log.warning("bm25_index_missing", path=str(p))
            return
        with p.open("rb") as f:
            data = pickle.load(f)
        self.bm25 = data["bm25"]
        self.bm25_ids = data["ids"]
        self.bm25_meta = data["meta"]
        log.info("bm25_loaded", docs=len(self.bm25_ids))

    def reload_bm25(self) -> None:
        self._load_bm25()

    def verify_embedding_model(self) -> None:
        stored = (self.coll.metadata or {}).get("embedding_model")
        if stored and stored != settings.embedding_model:
            log.warning(
                "embedding_model_mismatch",
                stored=stored,
                configured=settings.embedding_model,
                hint="run: make ingest-clear",
            )

    def _embed(self, texts: list[str]) -> list[list[float]]:
        r = http_client.post(
            f"{settings.lm_studio_url}/embeddings",
            json={"model": settings.embedding_model, "input": texts},
            headers=settings.lm_studio_headers,
        )
        r.raise_for_status()
        data = r.json()["data"]
        return [d["embedding"] for d in data]

    def _tokenize(self, text: str) -> list[str]:
        return [t.lower() for t in text.split() if t.strip()]

    def _bm25_search(self, query: str, framework: str | None, k: int) -> list[Hit]:
        if self.bm25 is None:
            return []
        tokens = self._tokenize(query)
        scores = self.bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        out: list[Hit] = []
        for idx, score in ranked:
            if score <= 0:
                continue
            meta = self.bm25_meta[idx]
            if framework and meta.get("framework") != framework:
                continue
            doc_id = self.bm25_ids[idx]
            out.append(Hit(
                id=doc_id, framework=meta["framework"], source_path=meta["source_path"],
                title=meta.get("title", ""), heading=meta.get("heading", ""),
                chunk_index=meta["chunk_index"], content=meta["content"],
                score=float(score),
            ))
            if len(out) >= k:
                break
        return out

    def _vector_search(self, query: str, framework: str | None, k: int) -> list[Hit]:
        qvec = self._embed([query])[0]
        where = {"framework": framework} if framework else None
        res = self.coll.query(query_embeddings=[qvec], n_results=k, where=where)
        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        out: list[Hit] = []
        for i, _id in enumerate(ids):
            m = metas[i]
            sim = max(0.0, 1.0 - float(dists[i]))
            out.append(Hit(
                id=_id, framework=m["framework"], source_path=m["source_path"],
                title=m.get("title", ""), heading=m.get("heading", ""),
                chunk_index=m["chunk_index"], content=docs[i], score=sim,
            ))
        return out

    def search(self, query: str, framework: str | None = None, limit: int = 5) -> list[Hit]:
        bm25_hits = self._bm25_search(query, framework, k=20)
        vec_hits = self._vector_search(query, framework, k=20)
        fused = self._rrf(bm25_hits, vec_hits)
        return fused[:limit]

    def _rrf(self, *lists: list[Hit]) -> list[Hit]:
        scores: dict[str, float] = defaultdict(float)
        index: dict[str, Hit] = {}
        for lst in lists:
            for rank, hit in enumerate(lst):
                scores[hit.id] += 1.0 / (settings.rrf_k + rank + 1)
                index[hit.id] = hit
        ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        out: list[Hit] = []
        for doc_id, s in ordered:
            h = index[doc_id]
            out.append(Hit(
                id=h.id, framework=h.framework, source_path=h.source_path,
                title=h.title, heading=h.heading, chunk_index=h.chunk_index,
                content=h.content, score=s,
            ))
        return out

    def get_document(self, framework: str, path: str) -> str:
        p = Path(settings.prepared_dir) / framework / path
        if not p.exists():
            raise FileNotFoundError(f"{p}")
        return p.read_text(encoding="utf-8")

    def list_sources(self) -> dict[str, list[str]]:
        res = self.coll.get(include=["metadatas"])
        out: dict[str, set[str]] = defaultdict(set)
        for m in res.get("metadatas", []):
            fw = m.get("framework")
            sp = m.get("source_path")
            if fw and sp:
                out[fw].add(sp)
        return {k: sorted(v) for k, v in out.items()}

    def collection_count(self) -> int:
        return self.coll.count()
