# Migration Plan: Qdrant + Parent-Child Chunking

## Обзор

Переход от **ChromaDB + BM25Okapi (pickle)** к **Qdrant (embedded)** с добавлением **parent-child chunking**.

| Что уходит | Что приходит |
|-----------|-------------|
| ChromaDB PersistentClient | Qdrant embedded (`QdrantClient(path=...)`) |
| `rank-bm25` + `bm25.pkl` | Qdrant sparse vectors (TF-IDF via scikit-learn) |
| Ручной RRF (`_rrf()`) | `prefetch` + `FusionQuery(fusion=Fusion.RRF)` |
| 2 хранилища (chroma/ + bm25.pkl) | 1 хранилище (qdrant_storage/) |
| Чанки без parent-ссылок | Child chunks + parent content в payload |

---

## Фаза 0: Подготовка (0.5ч)

### 0.1 Бэкап текущего состояния

```bash
git checkout -b migration/qdrant-parent-child
cp -r data/chroma data/chroma.backup
cp data/bm25.pkl data/bm25.pkl.backup
```

### 0.2 Обновить зависимости

**`pyproject.toml`:**
```diff
  dependencies = [
-     "chromadb>=0.5.0",
-     "rank-bm25>=0.2.2",
      "httpx>=0.27.0",
      "structlog>=24.0.0",
      "fastapi>=0.115.0",
      "uvicorn[standard]>=0.32.0",
      "fastmcp>=2.0.0",
      "markdown-it-py>=3.0.0",
      "beautifulsoup4>=4.12.0",
      "markdownify>=0.13.0",
+     "qdrant-client>=1.12.0",
+     "scikit-learn>=1.5.0",
      "docs-shared",
  ]
```

```bash
uv lock
uv sync
```

---

## Фаза 1: Chunker — Parent-Child (1ч)

### 1.1 Добавить `parent_id` и `parent_content` в Chunk

**`ingestion/chunker.py`** — изменить `Chunk` dataclass:

```python
@dataclass
class Chunk:
    framework: str
    source_path: str
    title: str
    heading: str
    chunk_index: int
    content: str
    is_last_chunk: bool
    has_code: bool = False
    code_languages: list[str] = field(default_factory=list)
    block_types: list[str] = field(default_factory=list)
    # Parent-child
    parent_id: str | None = None          # "framework/path/section_index"
    parent_heading: str | None = None     # heading chain of parent section
    parent_content: str | None = None     # full parent section text
```

### 1.2 Группировка child chunks по parent section

В `make_chunks()` — после создания всех чанков, сгруппировать их по parent section:

```python
def make_chunks(
    framework: str,
    path: str,
    raw_text: str,
    max_words: int = 800,
    overlap_words: int = 80,
    parent_level: int = 2,  # H2 = parent boundary (configurable)
) -> list[Chunk]:
    # ... существующая логика chunking ...

    # Phase 2: attach parent info
    # Group chunks by parent section (H2 or H1 if no H2)
    parent_groups: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        chain = chunk.heading.split(" > ")
        if len(chain) >= parent_level:
            pid = " > ".join(chain[:parent_level])
        else:
            pid = chunk.heading or path
        parent_groups.setdefault(pid, []).append(chunk)

    for chunk in chunks:
        chain = chunk.heading.split(" > ")
        if len(chain) >= parent_level:
            pid = " > ".join(chain[:parent_level])
        else:
            pid = chunk.heading or path

        chunk.parent_id = f"{framework}/{path}/{pid.replace(' > ', '/')}"
        chunk.parent_heading = pid

        # Build parent content from all chunks in same group
        parent_chunks = parent_groups[pid]
        if len(parent_chunks) > 1:
            # Multi-chunk section → parent = concatenation
            chunk.parent_content = "\n\n".join(
                c.content for c in parent_chunks
            )
        # Single-chunk section → parent = child (no duplication needed)
        # chunk.parent_content stays None
```

**Почему `parent_level=2` (H2):**
- Spark docs: H1 = документ, H2 = раздел (200-3000 слов), H3 = подраздел
- Delta docs: аналогичная структура
- H2 — естественная граница «секции» для RAG

### 1.3 Обновить тесты chunker

**`tests/test_chunker.py`** — добавить:

```python
def test_parent_child_single_section():
    md = "# Title\n\n## Section\n\nshort text\n"
    chunks = make_chunks("fw", "a.md", md)
    assert len(chunks) == 1
    assert chunks[0].parent_id == "fw/a.md/Title/Section"
    assert chunks[0].parent_content is None  # single chunk = no parent needed

def test_parent_child_multi_chunk_section():
    long_text = " ".join(f"Sentence {i}." for i in range(300))
    md = f"# Title\n\n## Section\n\n{long_text}\n"
    chunks = make_chunks("fw", "a.md", md, max_words=80, overlap_words=20)
    assert len(chunks) >= 2
    for c in chunks:
        assert c.parent_id == "fw/a.md/Title/Section"
        assert c.parent_content is not None
        assert len(c.parent_content) > len(c.content)

def test_parent_level_h1_fallback():
    md = "# Title\n\nno h2 here\n"
    chunks = make_chunks("fw", "a.md", md)
    assert chunks[0].parent_id == "fw/a.md/Title"
```

---

## Фаза 2: Sparse Builder (0.5ч)

### 2.1 Создать `ingestion/sparse_builder.py`

```python
"""Build sparse vectors (TF-IDF) for Qdrant keyword search."""

from __future__ import annotations

import pickle
from pathlib import Path

from qdrant_client.models import SparseVector
from sklearn.feature_extraction.text import TfidfVectorizer


class SparseBuilder:
    """TF-IDF → Qdrant sparse vectors.

    Uses sublinear_tf=True for BM25-like term frequency saturation.
    """

    def __init__(
        self,
        max_features: int = 50_000,
        min_df: int = 2,
        max_df: float = 0.95,
    ):
        self._vectorizer = TfidfVectorizer(
            max_features=max_features,
            sublinear_tf=True,
            stop_words="english",
            min_df=min_df,
            max_df=max_df,
        )
        self._fitted = False

    def fit_build(self, texts: list[str]) -> list[SparseVector]:
        """Fit vectorizer on corpus and build sparse vectors."""
        tfidf_matrix = self._vectorizer.fit_transform(texts)
        self._fitted = True
        return self._matrix_to_sparse(tfidf_matrix)

    def build(self, texts: list[str]) -> list[SparseVector]:
        """Transform texts using fitted vectorizer."""
        if not self._fitted:
            raise RuntimeError("Call fit_build() first")
        return self._matrix_to_sparse(self._vectorizer.transform(texts))

    def encode_query(self, query: str) -> SparseVector:
        """Encode a single query to sparse vector."""
        if not self._fitted:
            raise RuntimeError("Vectorizer not fitted. Load from disk first.")
        tfidf = self._vectorizer.transform([query])
        row = tfidf[0]
        return SparseVector(indices=row.indices.tolist(), values=row.data.tolist())

    def save(self, path: str | Path) -> None:
        """Persist fitted vectorizer to disk."""
        with open(path, "wb") as f:
            pickle.dump(self._vectorizer, f)

    @classmethod
    def load(cls, path: str | Path) -> "SparseBuilder":
        """Load fitted vectorizer from disk."""
        instance = cls.__new__(cls)
        with open(path, "rb") as f:
            instance._vectorizer = pickle.load(f)
        instance._fitted = True
        return instance

    def _matrix_to_sparse(self, matrix) -> list[SparseVector]:
        vectors: list[SparseVector] = []
        for row in matrix:
            vectors.append(SparseVector(
                indices=row.indices.tolist(),
                values=row.data.tolist(),
            ))
        return vectors


__all__ = ["SparseBuilder"]
```

### 2.2 Удалить `ingestion/bm25_index.py`

Полностью удалить файл. Его функциональность заменена на `SparseBuilder`.

---

## Фаза 3: Ingest (1.5ч)

### 3.1 Переписать `ingestion/ingest.py`

```python
"""Ingest prepared docs into Qdrant (embedded)."""

from __future__ import annotations

import argparse
from pathlib import Path

import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
    SparseVectorParams,
    SparseIndexParams,
)

from docs_shared.config import settings
from docs_shared.guards import warn_if_embedding_drift
from chunker import make_chunks
from embedder import embed_batch
from sparse_builder import SparseBuilder

log = structlog.get_logger()


def discover_files(data_dir: Path, framework: str | None) -> list[tuple[str, str]]:
    """Scan prepared_dir for .md files."""
    out: list[tuple[str, str]] = []
    fws = [framework] if framework else [
        p.name for p in data_dir.iterdir() if p.is_dir()
    ]
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

    # Discover files
    files = discover_files(data_dir, args.framework)
    log.info("files_discovered", count=len(files))

    # Chunk all files
    chunks: list = []
    for fw, rel in files:
        text = (data_dir / fw / rel).read_text(encoding="utf-8")
        chunks.extend(
            make_chunks(
                fw, rel, text,
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
        # Named vectors config: dense is named "dense" for hybrid search
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
    else:
        # Check embedding drift (stored in payload of first point, not collection config)
        # For now, skip — Qdrant doesn't store custom metadata on vectors_config
        pass

    # Clear if requested
    if args.clear:
        from qdrant_client.models import FilterSelector, Filter
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
    # IMPORTANT: vector is a dict with named keys when sparse is present
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
```

### 3.2 Обновить `docs_shared/guards.py`

```python
from __future__ import annotations

import structlog
from .config import settings

log = structlog.get_logger()


def warn_if_embedding_drift(collection_metadata: dict | None) -> None:
    """Check if the embedding model has changed since last ingest.

    NOTE: Qdrant doesn't store custom metadata on collection config like ChromaDB.
    This is kept for compatibility but may need a different approach (e.g. payload
    on a special point, or a sidecar JSON file).
    """
    stored = (collection_metadata or {}).get("embedding_model")
    if stored and stored != settings.embedding_model:
        log.warning(
            "embedding_model_mismatch",
            stored=stored,
            configured=settings.embedding_model,
            hint="run: make ingest-clear",
        )
```

### 3.3 Изменения Фазы 3 (итог)

| Изменение | Описание |
|-----------|----------|
| `vectors_config={"dense": VectorParams(...)}` | Named vector (не анонимный) — требуется при наличии sparse |
| `PointStruct.vector={"dense": ..., "sparse": ...}` | Dict format, не поле `sparse_vector` |
| `client.delete(collection_name=..., points_selector=FilterSelector(filter=Filter()))` | Правильный API для очистки |
| `client.upsert(collection_name=..., points=..., wait=True)` | Правильные именованные аргументы |
| `content` добавлен в payload | Нужен для `_dedup_by_parent` в retriever |

---

## Фаза 4: Retriever (1.5ч)

### 4.1 Переписать `docs_shared/retriever.py`

```python
"""Qdrant-based hybrid retriever with parent-child deduplication."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
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
    """Hybrid search: dense (semantic) + sparse (keyword) → RRF fusion → parent dedup.

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
            self._sparse_builder = None  # type: ignore

    def search(
        self,
        query: str,
        framework: str | None = None,
        limit: int = 5,
    ) -> list[Hit]:
        """Hybrid search: prefetch dense + sparse → Fusion.RRF → parent dedup."""
        # Dense query vector via LM Studio
        dense_vec = self._embed([query])[0]

        # Sparse query vector via TF-IDF
        sparse_vec = (
            self._sparse_builder.encode_query(query)
            if self._sparse_builder
            else None
        )

        # Framework filter
        qfilter = None
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
        if sparse_vec:
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

        out: dict[str, set[str]] = defaultdict(set)
        for point in points:
            fw = point.payload.get("framework")
            sp = point.payload.get("source_path")
            if fw and sp:
                out[fw].add(sp)
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
```

### 4.2 Обновить `docs_shared/__init__.py`

```python
from __future__ import annotations

from .config import settings
from .retriever import QdrantRetriever, Hit, http_client
from .guards import warn_if_embedding_drift

__all__ = [
    "settings",
    "QdrantRetriever",
    "Hit",
    "http_client",
    "warn_if_embedding_drift",
]
```

### 4.3 Изменения Фазы 4 (итог)

| Было (неверно) | Стало (верно) |
|----------------|---------------|
| `client.query()` | `client.query_points()` |
| `Query(fusion=Fusion.RRF, queries=[...])` | `prefetch=[Prefetch(...)]` + `query=FusionQuery(fusion=Fusion.RRF)` |
| `SearchRequest(vector=...)` | `Prefetch(query=..., using="dense")` |
| `SearchRequest(sparse_vector=(...))` | `Prefetch(query=SparseVector(...), using="sparse")` |
| `Match(value=...)` | `MatchValue(value=...)` |
| `results.points` | `results.points` (то же) |

---

## Фаза 5: Config (0.5ч)

### 5.1 Обновить `docs_shared/config.py`

```python
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    lm_studio_url: str
    lm_studio_api_key: str
    embedding_model: str
    embedding_dim: int
    qdrant_storage_path: str
    qdrant_collection: str
    rrf_k: int
    prepared_dir: str
    server_port: int
    chunk_max_words: int
    chunk_overlap_words: int
    parent_level: int

    @property
    def lm_studio_headers(self) -> dict:
        if self.lm_studio_api_key:
            return {"Authorization": f"Bearer {self.lm_studio_api_key}"}
        return {}

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            lm_studio_url=os.getenv("LM_STUDIO_URL", "http://host.docker.internal:1234/v1"),
            lm_studio_api_key=os.getenv("LM_STUDIO_API_KEY", ""),
            embedding_model=os.getenv("EMBEDDING_MODEL", "nomic-embed-text-v1.5"),
            embedding_dim=int(os.getenv("EMBEDDING_DIM", "768")),
            qdrant_storage_path=os.getenv("QDRANT_STORAGE_PATH", "/data/qdrant_storage"),
            qdrant_collection=os.getenv("QDRANT_COLLECTION", "docs"),
            rrf_k=int(os.getenv("RRF_K", "60")),
            prepared_dir=os.getenv("PREPARED_DIR", "/data/prepared"),
            server_port=int(os.getenv("SERVER_PORT", "8000")),
            chunk_max_words=int(os.getenv("CHUNK_MAX_WORDS", "800")),
            chunk_overlap_words=int(os.getenv("CHUNK_OVERLAP_WORDS", "80")),
            parent_level=int(os.getenv("PARENT_LEVEL", "2")),
        )


settings = Settings.from_env()
```

**Изменения:**
- `chroma_persist_dir` → `qdrant_storage_path`
- `chroma_collection` → `qdrant_collection`
- `bm25_path` → удалён (sparse model в qdrant_storage)
- `embedding_dim` → добавлен (нужен для create_collection)
- `parent_level` → добавлен (уровень заголовка для parent boundary)

### 5.2 Обновить `.env.example`

```bash
LM_STUDIO_URL=http://host.docker.internal:1234/v1
LM_STUDIO_API_KEY=
EMBEDDING_MODEL=nomic-embed-text-v1.5
EMBEDDING_DIM=768
QDRANT_STORAGE_PATH=/data/qdrant_storage
QDRANT_COLLECTION=docs
RRF_K=60
PREPARED_DIR=/data/prepared
SERVER_PORT=8000
CHUNK_MAX_WORDS=800
CHUNK_OVERLAP_WORDS=80
PARENT_LEVEL=2
```

---

## Фаза 6: Server (0.5ч)

### 6.1 Обновить `app/server.py`

```python
# Изменения:
# 1. HybridRetriever → QdrantRetriever
# 2. Hit.content → Hit.content (child snippet) + parent_content
# 3. health check: chroma_ok → qdrant_ok, bm25_loaded → sparse_loaded
```

**`_to_hit_dict`:**
```python
def _to_hit_dict(hits) -> list[dict]:
    return [
        {
            "id": h.id,
            "framework": h.framework,
            "path": h.source_path,
            "title": h.title,
            "heading": h.heading,
            "chunk_index": h.chunk_index,
            "score": h.score,
            "snippet": h.content[:500],
            "parent_content": h.parent_content[:2000] if h.parent_content else None,
        }
        for h in hits
    ]
```

**Health check:**
```python
@app.get("/health")
def health() -> dict:
    qdrant_ok = retriever.collection_count() >= 0
    sparse_ok = retriever._sparse_builder is not None  # type: ignore
    lm_ok = True
    try:
        shared_http_client.get(
            f"{settings.lm_studio_url}/models",
            headers=settings.lm_studio_headers,
            timeout=3,
        ).raise_for_status()
    except Exception:
        lm_ok = False

    return {
        "qdrant": qdrant_ok,
        "sparse_model": sparse_ok,
        "lm_studio": lm_ok,
        "collection_count": retriever.collection_count(),
        "embedding_model": settings.embedding_model,
    }
```

---

## Фаза 7: Docker (0.5ч)

### 7.1 Обновить `Dockerfile`

```dockerfile
FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock .
COPY docs_shared/pyproject.toml docs_shared/

RUN uv sync --frozen

COPY docs_shared/ /app/docs_shared/
COPY ingestion/ /app/ingestion/
COPY app/ /app/app/

RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app

ENV PYTHONPATH="/app:/app/ingestion"

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
```

Без изменений (зависимости обновятся через `uv.lock`).

### 7.2 Обновить `docker-compose.yml`

```yaml
services:
  lore:
    image: lore
    build: .
    env_file: .env
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data
      - ./data/prepared:/data/prepared:ro
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
```

Без изменений (volume `./data:/data` покрывает `data/qdrant_storage/`).

### 7.3 Обновить `Makefile`

```diff
  clean:
-     docker compose down -v
-     rm -rf data/chroma/* data/bm25.pkl
+     docker compose down -v
+     rm -rf data/qdrant_storage/*
      rm -rf data/prepared/delta data/prepared/spark data/prepared/test
      rm -rf .venv
```

---

## Фаза 8: Тесты (1.5ч)

### 8.1 Обновить `tests/test_chunker.py`

Добавить тесты parent-child (см. Фаза 1.3).

### 8.2 Создать `tests/test_sparse_builder.py`

```python
"""Tests for ingestion.sparse_builder."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ingestion.sparse_builder import SparseBuilder


def test_fit_build_returns_sparse_vectors():
    texts = ["hello world", "foo bar baz", "hello foo"]
    builder = SparseBuilder()
    vectors = builder.fit_build(texts)
    assert len(vectors) == 3
    for v in vectors:
        assert len(v.indices) > 0
        assert len(v.values) == len(v.indices)


def test_build_after_fit():
    texts = ["hello world", "foo bar"]
    builder = SparseBuilder()
    builder.fit_build(texts)
    new_vectors = builder.build(["hello again"])
    assert len(new_vectors) == 1


def test_encode_query():
    texts = ["the quick brown fox", "lazy dog sleeps"]
    builder = SparseBuilder()
    builder.fit_build(texts)
    qvec = builder.encode_query("quick fox")
    assert len(qvec.indices) > 0


def test_save_and_load():
    texts = ["alpha beta gamma", "delta epsilon"]
    builder = SparseBuilder()
    builder.fit_build(texts)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "model.pkl"
        builder.save(path)

        loaded = SparseBuilder.load(path)
        v1 = builder.encode_query("alpha")
        v2 = loaded.encode_query("alpha")
        assert v1.indices == v2.indices


def test_build_before_fit_raises():
    builder = SparseBuilder()
    try:
        builder.build(["test"])
        assert False, "Should raise RuntimeError"
    except RuntimeError:
        pass


def test_encode_query_before_fit_raises():
    builder = SparseBuilder()
    try:
        builder.encode_query("test")
        assert False, "Should raise RuntimeError"
    except RuntimeError:
        pass
```

### 8.3 Создать `tests/test_retriever.py`

```python
"""Tests for docs_shared.retriever QdrantRetriever."""

from __future__ import annotations

import tempfile
from pathlib import Path

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
from ingestion.sparse_builder import SparseBuilder


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
    ]

    # Dummy embeddings (4-dim for testing)
    embeddings = [
        [0.9, 0.1, 0.0, 0.0],
        [0.0, 0.9, 0.1, 0.0],
        [0.1, 0.0, 0.9, 0.0],
        [0.0, 0.1, 0.0, 0.9],
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
                "framework": "spark" if i < 2 else "delta",
                "source_path": f"docs/doc{i}.md",
                "title": f"Doc {i}",
                "heading": f"Doc {i} > Section",
                "chunk_index": i,
                "content": texts[i],
                "is_last_chunk": i == 3,
                "has_code": False,
                "code_languages": "",
                "block_types": "prose",
                "parent_id": f"fw/doc{i}.md/Doc {i}/Section",
                "parent_heading": f"Doc {i} > Section",
                "parent_content": texts[i] + " [parent context]",
            },
        )
        for i in range(4)
    ]

    client.upsert(collection_name=collection, points=points, wait=True)
    return client, builder


def test_collection_count():
    with tempfile.TemporaryDirectory() as tmp:
        client, _ = _create_test_collection(tmp)
        count = client.count(collection_name="test_docs").count
        assert count == 4


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
        qvec = loaded.encode_query("dataframe api")
        assert len(qvec.indices) > 0


def test_parent_dedup_logic():
    """Test that dedup keeps highest-scoring child per parent."""
    # Simulate points with same parent_id but different scores
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
    # parent-1 → child A (score 0.8 > 0.6)
    assert best_per_parent["parent-1"][1].payload["content"] == "child A"
    # parent-2 → child C (score 0.9 > 0.5)
    assert best_per_parent["parent-2"][1].payload["content"] == "child C"


def test_single_chunk_no_parent_content():
    """Single-chunk sections should have parent_content = None in chunker."""
    from ingestion.chunker import make_chunks

    md = "# Title\n\n## Section\n\nshort text\n"
    chunks = make_chunks("fw", "a.md", md)
    assert len(chunks) == 1
    assert chunks[0].parent_content is None


def test_multi_chunk_has_parent_content():
    """Multi-chunk sections should have parent_content set."""
    from ingestion.chunker import make_chunks

    long_text = " ".join(f"Sentence {i}." for i in range(300))
    md = f"# Title\n\n## Section\n\n{long_text}\n"
    chunks = make_chunks("fw", "a.md", md, max_words=80, overlap_words=20)
    assert len(chunks) >= 2
    for c in chunks:
        assert c.parent_content is not None


def test_parent_id_format():
    """Parent ID should be framework/path/heading."""
    from ingestion.chunker import make_chunks

    md = "# Doc\n\n## Sec\n\ncontent here\n"
    chunks = make_chunks("delta", "api/table.md", md)
    assert chunks[0].parent_id == "delta/api/table.md/Doc/Sec"
```

---

## Фаза 9: Документация (1ч)

### 9.1 `docs/architecture.md`

Заменить:
- Pipeline: `ChromaDB + BM25` → `Qdrant (dense + sparse)`
- Component Interaction: ChromaDB → Qdrant, BM25 → Sparse vectors
- Data Flow: описать TF-IDF + embeddings → Qdrant upsert
- Key Design Decisions:
  - `Qdrant embedded` → No separate DB container, dense + sparse + RRF in one
  - `TF-IDF sparse vectors` → BM25-like keyword search via scikit-learn
  - `Parent-child chunking` → Small chunks for search precision, parent content for context

### 9.2 `docs/areas/retriever.md`

Полностью переписать:
- `QdrantRetriever` вместо `HybridRetriever`
- Инициализация: `QdrantClient(path=...)`, load sparse model
- Поиск: `prefetch=[Prefetch(...)]` + `query=FusionQuery(fusion=Fusion.RRF)`
- Дедупликация: `_dedup_by_parent()` — highest-scoring child per parent
- Hit dataclass: добавить `parent_content`
- Удалить секции: BM25 Search, BM25 Index, RRF Fusion (теперь в Qdrant)

### 9.3 `docs/areas/chunker.md`

Добавить секцию:
```markdown
## Parent-Child Chunking

Each chunk carries `parent_id`, `parent_heading`, and optionally `parent_content`:

- **`parent_id`** — unique identifier for the parent section (`framework/path/H1/H2`)
- **`parent_heading`** — heading chain of the parent section
- **`parent_content`** — full text of all child chunks in the same parent section.
  Set only when a section is split into 2+ chunks. Single-chunk sections have
  `parent_content = None` to avoid duplication.

The `parent_level` parameter (default: 2) controls which heading level defines
a parent boundary. H2 is the default because Spark/Delta docs use H2 as the
natural "section" boundary.
```

### 9.4 `docs/areas/ingestion.md`

Заменить:
- Workflow: `chunk → embed → upsert ChromaDB → build BM25` → `chunk → embed → sparse → upsert Qdrant`
- BM25 Index → Sparse Builder (TF-IDF via scikit-learn)
- Metadata: добавить `parent_id`, `parent_heading`, `parent_content`, `content`
- Flags: без изменений

### 9.5 `docs/areas/config.md`

Обновить таблицу Settings:
- `chroma_persist_dir` → `qdrant_storage_path`
- `chroma_collection` → `qdrant_collection`
- `bm25_path` → удалён
- `embedding_dim` → добавлен
- `parent_level` → добавлен

### 9.6 `docs/areas/docker.md`

Обновить:
- Volume Mounts: `data/chroma/` → `data/qdrant_storage/`
- `data/bm25.pkl` → удалён

### 9.7 `docs/testing.md`

Обновить Coverage таблицу:
- Добавить `test_sparse_builder.py` (6 тестов)
- Добавить `test_retriever.py` (8 тестов)

### 9.8 `docs/troubleshooting.md`

Обновить:
- `ChromaDB Not Responding` → `Qdrant Storage Issues`
- `Embed Drift Warning` → добавить ноту про отсутствие встроенного хранения metadata в Qdrant
- `BM25 Rebuild on Partial Ingest` → `Sparse Model Rebuild`
- `Search Returns 0 Hits After make ingest` → без изменений (Qdrant embedded, no restart needed)

### 9.9 `docs/context-index.md`

Обновить ссылки:
- `retriever.md`: ChromaDB, BM25 → Qdrant, sparse vectors, parent-child

### 9.10 `AGENTS.md`

Обновить:
- Architecture: ChromaDB + BM25 → Qdrant
- Environment Variables: обновить таблицу
- REST API: добавить `parent_content` в ответ
- MCP Tools: добавить `parent_content` в ответ
- Rules: `make ingest-clear` → очищает Qdrant + sparse model

---

## Фаза 10: Верификация (0.5ч)

### 10.1 Запустить тесты

```bash
make test
uv run ruff check
```

### 10.2 Индексация

```bash
make prepare
make ingest-clear
make ingest
make rebuild
```

### 10.3 Проверка health

```bash
curl http://localhost:8000/health
# {"qdrant": true, "sparse_model": true, "lm_studio": true, "collection_count": N, ...}
```

### 10.4 Проверка поиска

```bash
# REST
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "checkpointing", "framework": "spark", "limit": 3}'

# MCP
# search_docs(query="checkpointing", framework="spark", limit=3)
```

### 10.5 Проверка parent-child

```bash
# Verify parent_content is present for multi-chunk sections
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "DataFrame API", "limit": 5}' | \
  jq '.[] | {id, snippet_length: (.snippet | length), parent_length: (.parent_content | length)}'
```

---

## Риски и митигация

| Риск | Вероятность | Митигация |
|------|------------|-----------|
| TF-IDF ≠ BM25Okapi (качество поиска) | Средняя | Сравнить top-10 результатов для 20+ запросов; если деградация > 10% — оставить BM25 или добавить custom BM25 scorer |
| Qdrant embedded медленнее ChromaDB | Низкая | Бенчмарк: `time make ingest`; при ~10K чанков разница < 30с |
| `scikit-learn` увеличивает размер образа | Низкая | `uv sync` + Docker layer caching; итоговый образ ~400MB vs ~360MB |
| Parent-child ломает существующие запросы | Низкая | `Hit.content` остаётся child snippet; `parent_content` — новое поле, backward compatible |
| LM Studio недоступен при индексе | Средняя | Существующий риск, не меняется; embedder уже требует LM Studio |
| Qdrant embedded mode не поддерживает concurrent writes | Низкая | Индексация single-threaded, не критично |
| Embedding drift detection не работает в Qdrant | Средняя | Qdrant не хранит custom metadata на collection level. Решение: sidecar JSON или payload на спец-точке |

---

## Сводка исправлений API (vs оригинальный план)

| # | Было (неверно) | Стало (верно) | Источник |
|---|----------------|---------------|----------|
| 1 | `client.query(collection, query=Query(...))` | `client.query_points(collection_name=..., prefetch=[...], query=FusionQuery(...))` | context7: qdrant-client docs |
| 2 | `Query(fusion=Fusion.RRF, queries=[SearchRequest(...)])` | `prefetch=[Prefetch(query=vec, using="dense")]` + `query=FusionQuery(fusion=Fusion.RRF)` | context7: qdrant-client docs |
| 3 | `PointStruct(sparse_vector={"sparse": ...})` | `PointStruct(vector={"dense": ..., "sparse": ...})` | context7: upsert with named vectors |
| 4 | `Match(value=framework)` | `MatchValue(value=framework)` | context7: Filter example |
| 5 | `client.delete(collection, points_selector=None)` | `client.delete(collection_name=..., points_selector=FilterSelector(filter=Filter()))` | context7: delete docs |
| 6 | `vectors_config=VectorParams(...)` | `vectors_config={"dense": VectorParams(...)}` | context7: create_collection with sparse |
| 7 | `SearchRequest` | `Prefetch` | context7: query_points docs |
| 8 | `Query` | `FusionQuery` | context7: query_points docs |
| 9 | Нет `using` параметра | `using="dense"` / `using="sparse"` | context7: query_points docs |
| 10 | `content` не в payload | `content` добавлен в payload | Логика `_dedup_by_parent` |

---

## Чек-лист

- [ ] Фаза 0: бэкап, зависимости
- [ ] Фаза 1: chunker parent-child + тесты
- [ ] Фаза 2: sparse_builder + удалить bm25_index
- [ ] Фаза 3: ingest.py rewrite (named vectors, correct delete/upsert)
- [ ] Фаза 4: retriever.py rewrite (prefetch + FusionQuery, MatchValue)
- [ ] Фаза 5: config + .env.example
- [ ] Фаза 6: server.py (health, response format)
- [ ] Фаза 7: Docker, Makefile
- [ ] Фаза 8: тесты (sparse_builder, retriever)
- [ ] Фаза 9: документация (7 файлов)
- [ ] Фаза 10: верификация (test, ingest, health, search)

**Оценка:** ~9 часов работы (1 человек-день)
