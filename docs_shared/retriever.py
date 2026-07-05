"""Qdrant-based hybrid retriever with parent-child deduplication."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from qdrant_client import AsyncQdrantClient
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
from .embedder import Embedder
from .exceptions import DocumentNotFoundError, QdrantError
from .sparse_builder import SparseBuilder

log = structlog.get_logger()


@dataclass
class Hit:
    id: int | str
    framework: str
    source_path: str
    title: str
    heading: str
    chunk_index: int
    content: str  # child chunk (precise match)
    parent_content: str  # full parent section (context)
    score: float


class QdrantRetriever:
    """Hybrid search: dense (semantic) + sparse (keyword) -> RRF fusion -> parent dedup.

    Uses Qdrant prefetch + FusionQuery for server-side RRF.
    Dense vector via FastEmbedEmbedder (local ONNX), sparse vector via TF-IDF (scikit-learn).
    """

    def __init__(self, embedder: Embedder | None = None) -> None:
        self.client = AsyncQdrantClient(path=settings.qdrant_storage_path)
        self.collection = settings.qdrant_collection
        self._embedder = embedder or Embedder()

        # Load sparse vectorizer
        sparse_path = Path(settings.qdrant_storage_path) / "sparse_model.pkl"
        builder: SparseBuilder | None
        if sparse_path.exists():
            builder = SparseBuilder.load(sparse_path)
        else:
            log.warning("sparse_model_missing", path=str(sparse_path))
            builder = None
        self._sparse_builder = builder

    async def search(
        self,
        query: str,
        framework: str | None = None,
        limit: int = 5,
    ) -> list[Hit]:
        """Hybrid search: prefetch dense + sparse -> Fusion.RRF -> parent dedup."""
        # Dense query vector via FastEmbedEmbedder
        dense_vec = await self._embedder.embed_one(query)

        # Sparse query vector via TF-IDF
        sparse_vec: SparseVector | None = (
            self._sparse_builder.encode_query(query) if self._sparse_builder else None
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
        fetch_limit = max(
            limit * settings.search_fetch_multiplier, settings.search_fetch_min
        )

        # Build prefetch queries
        # In qdrant-client >= 1.18, query_filter on query_points with FusionQuery
        # is silently dropped. The filter must be applied per-Prefetch.
        prefetch_queries: list[Prefetch] = [
            Prefetch(query=dense_vec, using="dense", limit=fetch_limit, filter=qfilter),
        ]
        if sparse_vec is not None:
            prefetch_queries.append(
                Prefetch(
                    query=sparse_vec, using="sparse", limit=fetch_limit, filter=qfilter
                )
            )

        # Qdrant server-side RRF fusion via prefetch + FusionQuery
        results = await self.client.query_points(
            collection_name=self.collection,
            prefetch=prefetch_queries,
            query=FusionQuery(fusion=Fusion.RRF),
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

            hits.append(
                Hit(
                    id=point.id,
                    framework=payload["framework"],
                    source_path=payload["source_path"],
                    title=payload.get("title", ""),
                    heading=payload.get("heading", ""),
                    chunk_index=payload.get("chunk_index", 0),
                    content=content,
                    parent_content=parent_content,
                    score=float(point.score),
                )
            )

        return hits

    def get_document(self, framework: str, path: str) -> str:
        """Read full document from prepared directory.

        Resolves paths and blocks traversal outside the prepared directory.
        """
        base = Path(settings.prepared_dir).resolve()
        p = (base / framework / path).resolve()
        if not p.is_relative_to(base):
            raise DocumentNotFoundError(f"Document not found: {path}")
        if not p.is_file():
            raise DocumentNotFoundError(f"Document not found: {path}")
        return p.read_text(encoding="utf-8")

    async def list_sources(self) -> dict[str, list[str]]:
        """List all indexed frameworks and their source paths."""
        try:
            out: dict[str, set[str]] = {}
            offset = None
            while True:
                scroll_results = await self.client.scroll(
                    collection_name=self.collection,
                    limit=1000,
                    offset=offset,
                    with_payload=["framework", "source_path"],
                    with_vectors=False,
                )
                points, next_offset = scroll_results
                for point in points:
                    fw = point.payload.get("framework")
                    sp = point.payload.get("source_path")
                    if fw and sp:
                        out.setdefault(fw, set()).add(sp)
                if not next_offset:
                    break
                offset = next_offset
        except Exception as e:
            raise QdrantError(f"Failed to list sources: {e}") from e
        return {k: sorted(v) for k, v in out.items()}

    async def collection_count(self) -> int:
        """Return number of points in the collection."""
        try:
            count_result = await self.client.count(collection_name=self.collection)
            return count_result.count
        except Exception as e:
            raise QdrantError(f"Failed to get collection count: {e}") from e

    async def aclose(self) -> None:
        """Close async resources."""
        await self.client.close()

    def is_sparse_model_loaded(self) -> bool:
        """Check if the sparse (TF-IDF) model was loaded successfully."""
        return self._sparse_builder is not None

    def verify_embedding_model(self) -> bool:
        """Check embedding model consistency against sidecar metadata.

        Returns True if consistent or no index exists yet.
        Returns False if model/dim mismatch is detected.
        """
        model_info_path = Path(settings.qdrant_storage_path) / ".model_info.json"
        if not model_info_path.exists():
            log.info("no_model_info", hint="run: make ingest")
            return True

        try:
            info = json.loads(model_info_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log.error("model_info_corrupt", error=str(e))
            return False

        stored_model = info.get("embedding_model")
        stored_dim = info.get("embedding_dim")

        if stored_model and stored_model != settings.embedding_model:
            log.warning(
                "embedding_model_mismatch",
                stored=stored_model,
                configured=settings.embedding_model,
                hint="run: make ingest-clear",
            )
            return False

        if stored_dim and stored_dim != settings.embedding_dim:
            log.warning(
                "embedding_dim_mismatch",
                stored=stored_dim,
                configured=settings.embedding_dim,
                hint="run: make ingest-clear",
            )
            return False

        return True
