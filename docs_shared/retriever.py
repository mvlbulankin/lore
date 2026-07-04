"""Qdrant-based hybrid retriever with parent-child deduplication."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchValue,
    Prefetch,
    SparseVector,
)

from .config import settings
from ingestion.sparse_builder import SparseBuilder

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
    content: str           # child chunk (precise match)
    parent_content: str    # full parent section (context)
    score: float


class QdrantRetriever:
    """Hybrid search: dense (semantic) + sparse (keyword) -> RRF fusion -> parent dedup.

    Uses Qdrant prefetch + FusionQuery for server-side RRF.
    Dense vector via LM Studio, sparse vector via TF-IDF (scikit-learn).
    """

    def __init__(self) -> None:
        self.client = QdrantClient(path=settings.qdrant_storage_path)
        self.collection = settings.qdrant_collection

        # Load sparse vectorizer
        sparse_path = Path(settings.qdrant_storage_path) / "sparse_model.pkl"
        if sparse_path.exists():
            self._sparse_builder = SparseBuilder.load(sparse_path)
        else:
            log.warning("sparse_model_missing", path=str(sparse_path))
            self._sparse_builder = None  # type: ignore[assignment]

    def search(
        self,
        query: str,
        framework: str | None = None,
        limit: int = 5,
    ) -> list[Hit]:
        """Hybrid search: prefetch dense + sparse -> Fusion.RRF -> parent dedup."""
        # Dense query vector via LM Studio
        dense_vec = self._embed([query])[0]

        # Sparse query vector via TF-IDF
        sparse_vec: SparseVector | None = (
            self._sparse_builder.encode_query(query)
            if self._sparse_builder
            else None
        )

        # Framework filter
        qfilter: Filter | None = None
        if framework:
            qfilter = Filter(
                must=[
                    FieldCondition(key="framework", match=MatchValue(value=framework))
                ]
            )

        # Fetch more than limit to allow deduplication after parent grouping
        fetch_limit = max(limit * 4, 20)

        # Build prefetch queries
        prefetch_queries: list[Prefetch] = [
            Prefetch(query=dense_vec, using="dense", limit=fetch_limit),
        ]
        if sparse_vec is not None:
            prefetch_queries.append(
                Prefetch(query=sparse_vec, using="sparse", limit=fetch_limit)
            )

        # Qdrant server-side RRF fusion via prefetch + FusionQuery
        results = self.client.query_points(
            collection_name=self.collection,
            prefetch=prefetch_queries,
            query=FusionQuery(fusion=Fusion.RRF),
            query_filter=qfilter,
            limit=fetch_limit,
            with_payload=True,
        )

        # Parent-child deduplication
        hits = self._dedup_by_parent(results.points, limit)
        return hits

    def _dedup_by_parent(
        self,
        points: list[Any],
        limit: int,
    ) -> list[Hit]:
        """Deduplicate by parent_id, keeping highest-scoring child per parent.

        Returns child content (precise match) + parent content (full context).
        """
        best_per_parent: dict[str, tuple[float, Any]] = {}

        for point in points:
            pid = point.payload.get("parent_id", "")
            if not pid:
                pid = str(point.id)  # fallback: treat as own parent

            current_score = best_per_parent.get(pid, (0.0, None))[0]
            if point.score > current_score:
                best_per_parent[pid] = (point.score, point)

        # Sort by score, take top N
        sorted_parents = sorted(
            best_per_parent.values(), key=lambda x: x[0], reverse=True
        )[:limit]

        hits: list[Hit] = []
        for _score, point in sorted_parents:
            payload = point.payload
            content = payload.get("content", "")
            parent_content = payload.get("parent_content", "") or content

            hits.append(Hit(
                id=str(point.id),
                framework=payload["framework"],
                source_path=payload["source_path"],
                title=payload.get("title", ""),
                heading=payload.get("heading", ""),
                chunk_index=payload.get("chunk_index", 0),
                content=content,
                parent_content=parent_content,
                score=float(point.score),
            ))

        return hits

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts via LM Studio."""
        r = http_client.post(
            f"{settings.lm_studio_url}/embeddings",
            json={"model": settings.embedding_model, "input": texts},
            headers=settings.lm_studio_headers,
        )
        r.raise_for_status()
        data = r.json()["data"]
        return [d["embedding"] for d in data]

    def get_document(self, framework: str, path: str) -> str:
        """Read full document from prepared directory."""
        p = Path(settings.prepared_dir) / framework / path
        if not p.exists():
            raise FileNotFoundError(f"Document not found: {p}")
        return p.read_text(encoding="utf-8")

    def list_sources(self) -> dict[str, list[str]]:
        """List all indexed frameworks and their source paths."""
        scroll_results = self.client.scroll(
            collection_name=self.collection,
            limit=10000,
            with_payload=["framework", "source_path"],
            with_vectors=False,
        )
        points, _next_offset = scroll_results

        out: dict[str, set[str]] = {}
        for point in points:
            fw = point.payload.get("framework")
            sp = point.payload.get("source_path")
            if fw and sp:
                out.setdefault(fw, set()).add(sp)
        return {k: sorted(v) for k, v in out.items()}

    def collection_count(self) -> int:
        """Return number of points in the collection."""
        count_result = self.client.count(collection_name=self.collection)
        return count_result.count

    def verify_embedding_model(self) -> None:
        """Check embedding model consistency.

        NOTE: Qdrant doesn't store custom metadata on collection config.
        Consider storing model info in a sidecar JSON file or payload on a
        special point for drift detection.
        """
        pass
