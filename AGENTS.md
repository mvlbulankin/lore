# Lore — План реализации

Локальный RAG-сервер документации с MCP-интерфейсом для агентов (opencode и др.).

**Текущая архитектура:** один Docker-контейнер, ChromaDB PersistentClient (in-process), FastAPI + FastMCP, hybrid retrieval (BM25 + Vector + RRF).

## Решения

| Слой | Решение |
|------|---------|
| Vector DB | ChromaDB `PersistentClient` (in-process) |
| Embedding | `nomic-embed-text-v1.5` (768 dims) через LM Studio |
| Retrieval | Hybrid: BM25 + Vector + RRF (k=60) |
| BM25 storage | `data/bm25.pkl`, full rebuild при каждом ingest |
| Chunking | Code-aware: H1>H2>H3 chain в metadata, H4 labels приклеиваются к code-fence, code-fence атомарный, prose с sentence-overlap |
| MCP SDK | FastMCP, mounted в FastAPI на `/mcp` |
| HTTP client | httpx с retry (3 retries) |
| Embed drift | Detect при старте + warning в логи |
| Файлы | только `.md` в `data/prepared/{framework}/` |
| API | FastAPI (REST) + uvicorn |
| Container | Один образ, python:3.14-slim + uv |
| Re-ingest | Ручной через `docker compose run --rm lore python /app/ingestion/ingest.py` |
| Web UI | Нет |
| Machine | 16 GB RAM, RTX 5090 (32 GB VRAM) |
| Python | 3.14 |
| Package manager | uv workspace (dev + Docker) |
| Project layout | Root `pyproject.toml` workspace + `docs_shared/` как member |
| Подготовка | Per-framework preparer (Protocol), staging + atomic rename, запускается на хосте через uv |
| Layout | `data/source/` (сырьё) → `preparers/` (подготовка) → `data/prepared/` (готовые .md) → `ingestion/` (индексация) → ChromaDB |

---

## Структура проекта

```
lore/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── .python-version
├── Makefile
├── README.md
├── pyproject.toml          # workspace root + все deps
├── uv.lock                 # единый lock-файл
├── data/
│   ├── source/             # сырьё (Jekyll, MDX, Python) — read-only
│   │   ├── spark/docs/
│   │   ├── delta/docs/
│   │   ├── delta/examples/
│   │   └── test/
│   ├── prepared/           # выход preparers (готовые .md)
│   │   ├── spark/
│   │   ├── delta/
│   │   └── test/
│   ├── chroma/             # ChromaDB persistent storage
│   └── bm25.pkl            # BM25 index (generated)
├── docs_shared/            # общий пакет (workspace member)
│   ├── pyproject.toml
│   ├── __init__.py
│   ├── config.py
│   ├── retriever.py
│   └── guards.py
├── ingestion/              # индексация документов (скрипты, без pyproject.toml)
│   ├── chunker.py
│   ├── embedder.py
│   ├── bm25_index.py
│   └── ingest.py
├── app/                    # единый сервер (MCP + REST)
│   └── server.py
├── preparers/              # подготовка документов (на хосте, через uv)
│   ├── base.py             # FrameworkPreparer Protocol
│   ├── registry.py         # автодискавери
│   ├── cli.py              # python -m preparers.cli
│   ├── _atomic.py          # staging + atomic rename
│   ├── delta/
│   │   ├── README.md
│   │   └── prepare.py
│   ├── spark/
│   │   ├── README.md
│   │   └── prepare.py
│   └── test/
│       └── prepare.py
└── tests/                  # pytest
    ├── conftest.py
    ├── test_chunker.py
    └── test_preparer_base.py
```

---

## Шаг 1. Инициализация проекта

```bash
mkdir -p /Users/mvl/code/lore/{data/raw/{spark,delta},data/chroma,docs_shared,ingestion,app,preparation_scripts}
cd /Users/mvl/code/lore
```

Создать корневой `.python-version`:
```
3.14
```

Создать `.env.example`:
```bash
LM_STUDIO_URL=http://host.docker.internal:1234/v1
LM_STUDIO_API_KEY=
EMBEDDING_MODEL=nomic-embed-text-v1.5
CHROMA_PERSIST_DIR=/data/chroma
CHROMA_COLLECTION=docs
RRF_K=60
DATA_DIR=/data/raw
BM25_PATH=/data/bm25.pkl
SERVER_PORT=8000
CHUNK_MAX_WORDS=800
CHUNK_OVERLAP_WORDS=80
```

---

## Шаг 2. `Makefile`

```makefile
.PHONY: install lock up down ingest ingest-clear logs test clean

install:
	uv sync

lock:
	uv lock

up:
	docker compose up -d

down:
	docker compose down

ingest:
	docker compose run --rm lore sh -c 'PYTHONPATH=/app python /app/ingestion/ingest.py'

ingest-clear:
	docker compose run --rm lore sh -c 'PYTHONPATH=/app python /app/ingestion/ingest.py --clear'

logs:
	docker compose logs -f lore

test:
	uv run pytest

clean:
	docker compose down -v
	rm -rf data/chroma/* data/bm25.pkl
	rm -rf .venv
```

---

## Шаг 3. `docker-compose.yml`

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
      - ./data/raw:/data/raw:ro
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
```

---

## Шаг 4. `docs_shared/` пакет (workspace member)

### `docs_shared/pyproject.toml`
```toml
[project]
name = "docs-shared"
version = "0.1.0"
requires-python = ">=3.14,<3.15"
dependencies = []

[tool.hatch.build.targets.wheel]
packages = ["."]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### `docs_shared/__init__.py`
```python
from __future__ import annotations

from .config import settings
from .retriever import HybridRetriever, Hit, http_client
from .guards import warn_if_embedding_drift

__all__ = [
    "settings",
    "HybridRetriever",
    "Hit",
    "http_client",
    "warn_if_embedding_drift",
]
```

### `docs_shared/config.py`
```python
from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    lm_studio_url: str
    lm_studio_api_key: str
    embedding_model: str
    chroma_persist_dir: str
    chroma_collection: str
    rrf_k: int
    data_dir: str
    bm25_path: str
    server_port: int
    chunk_max_words: int
    chunk_overlap_words: int

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
            chroma_persist_dir=os.getenv("CHROMA_PERSIST_DIR", "/data/chroma"),
            chroma_collection=os.getenv("CHROMA_COLLECTION", "docs"),
            rrf_k=int(os.getenv("RRF_K", "60")),
            data_dir=os.getenv("DATA_DIR", "/data/raw"),
            bm25_path=os.getenv("BM25_PATH", "/data/bm25.pkl"),
            server_port=int(os.getenv("SERVER_PORT", "8000")),
            chunk_max_words=int(os.getenv("CHUNK_MAX_WORDS", "800")),
            chunk_overlap_words=int(os.getenv("CHUNK_OVERLAP_WORDS", "80")),
        )

settings = Settings.from_env()
```

### `docs_shared/retriever.py`
```python
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
        p = Path(settings.data_dir) / framework / path
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
```

### `docs_shared/guards.py`
```python
from __future__ import annotations
import structlog
from .config import settings

log = structlog.get_logger()

def warn_if_embedding_drift(collection_metadata: dict | None) -> None:
    stored = (collection_metadata or {}).get("embedding_model")
    if stored and stored != settings.embedding_model:
        log.warning(
            "embedding_model_mismatch",
            stored=stored,
            configured=settings.embedding_model,
            hint="run: make ingest-clear",
        )
```

---

## Шаг 5. `ingestion/` скрипты

### `ingestion/chunker.py`
```python
from __future__ import annotations

from dataclasses import dataclass

from markdown_it import MarkdownIt


@dataclass
class Chunk:
    framework: str
    source_path: str
    title: str
    heading: str
    chunk_index: int
    content: str
    is_last_chunk: bool


@dataclass
class _Section:
    heading_chain: str
    content_blocks: list[str]


def _parse_sections(text: str) -> tuple[str, list[_Section]]:
    """Parse markdown into (document_title, [sections]).

    Each section captures the heading chain (H1 > H2 > H3) and the content
    blocks that belong under that heading.

    Code blocks (fence tokens) are included in content.
    Headings deeper than H3 are treated as inline labels (e.g. "Scala", "Python"
    before code blocks) and are NOT added to the heading chain.
    """
    md = MarkdownIt()
    tokens = md.parse(text)

    document_title = ""
    sections: list[_Section] = []
    heading_stack: list[str] = []
    current_content: list[str] = []
    expect_heading_text = False
    max_heading_level = 3

    def _flush() -> None:
        nonlocal current_content
        if current_content:
            sections.append(_Section(
                heading_chain=" > ".join(heading_stack) if heading_stack else "",
                content_blocks=list(current_content),
            ))
            current_content = []

    for tok in tokens:
        if tok.type == "heading_open":
            _flush()
            level = int(tok.tag[1])
            if level <= len(heading_stack):
                heading_stack = heading_stack[: level - 1]
            expect_heading_text = True
            expect_heading_text = expect_heading_text and level <= max_heading_level

        elif tok.type == "heading_close":
            expect_heading_text = False

        elif tok.type == "inline" and tok.content.strip():
            stripped = tok.content.strip()
            if expect_heading_text:
                text = stripped
                if not heading_stack:
                    document_title = text
                heading_stack.append(text)
            else:
                current_content.append(stripped)

        elif tok.type == "fence" and tok.content.strip():
            current_content.append(tok.content.strip())

    _flush()

    return document_title, sections


def _split_by_words(
    text: str,
    max_words: int,
    overlap_words: int,
) -> list[str]:
    """Split a text block into chunks of max_words with overlap."""
    words = text.split()
    if len(words) <= max_words:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = start + max_words
        chunk_words = words[start:end]
        chunks.append(" ".join(chunk_words))
        start = end - overlap_words
    return chunks


def split_markdown(
    text: str,
    max_words: int = 800,
    overlap_words: int = 80,
) -> list[tuple[str, str]]:
    """Split markdown into (heading_chain, content) chunks.

    1. Parse document structure via markdown-it
    2. Split by H2/H3 headings, preserving heading chain in metadata
    3. Sub-split large sections by word count with overlap
    """
    _, sections = _parse_sections(text)

    if not sections:
        return [("", text)]

    result: list[tuple[str, str]] = []

    for section in sections:
        full_text = " ".join(section.content_blocks)
        if not full_text.strip():
            continue

        sub_chunks = _split_by_words(full_text, max_words, overlap_words)
        for sub in sub_chunks:
            result.append((section.heading_chain, sub))

    return result


def make_chunks(
    framework: str,
    path: str,
    raw_text: str,
    max_words: int = 800,
    overlap_words: int = 80,
) -> list[Chunk]:
    """Create typed Chunk objects from a markdown file.

    Extracts H1 as document title, preserves heading chain per chunk,
    and marks the last chunk of the file.
    """
    document_title, _ = _parse_sections(raw_text)
    title = document_title if document_title else path.replace("/", "_").replace(".md", "")

    pairs = split_markdown(raw_text, max_words, overlap_words)

    if not pairs:
        return []

    chunks = [
        Chunk(
            framework=framework,
            source_path=path,
            title=title,
            heading=heading_chain,
            chunk_index=i,
            content=content,
            is_last_chunk=False,
        )
        for i, (heading_chain, content) in enumerate(pairs)
    ]

    if chunks:
        chunks[-1] = Chunk(
            framework=chunks[-1].framework,
            source_path=chunks[-1].source_path,
            title=chunks[-1].title,
            heading=chunks[-1].heading,
            chunk_index=chunks[-1].chunk_index,
            content=chunks[-1].content,
            is_last_chunk=True,
        )

    return chunks
```

### `ingestion/embedder.py`
```python
from __future__ import annotations

from docs_shared.config import settings
from docs_shared import http_client

def embed_batch(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        r = http_client.post(
            f"{settings.lm_studio_url}/embeddings",
            json={"model": settings.embedding_model, "input": batch},
            headers=settings.lm_studio_headers,
        )
        r.raise_for_status()
        data = r.json()["data"]
        out.extend(d["embedding"] for d in data)
    return out
```

### `ingestion/bm25_index.py`
```python
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
```

### `ingestion/ingest.py`
```python
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

    data_dir = Path(settings.data_dir)
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
```

---

## Шаг 6. `app/` — единый сервер (MCP + REST)

### `app/server.py`
```python
from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from fastmcp import FastMCP
from fastmcp.utilities.lifespan import combine_lifespans

from docs_shared.retriever import HybridRetriever
from docs_shared.config import settings
from docs_shared import http_client as shared_http_client

structlog.configure(
    cache_logger_on_first_use=True,
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger("INFO"),
    logger_factory=structlog.PrintLoggerFactory(),
)

retriever = HybridRetriever()
retriever.verify_embedding_model()

mcp = FastMCP("lore")
mcp_app = mcp.http_app(path="/")

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    yield
    shared_http_client.close()

app = FastAPI(
    title="Docs API",
    lifespan=combine_lifespans(app_lifespan, mcp_app.lifespan),
)
app.mount("/mcp", mcp_app)

class SearchRequest(BaseModel):
    query: str
    framework: str | None = None
    limit: int = Field(default=5, ge=1, le=100)

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
        }
        for h in hits
    ]

@mcp.tool()
def search_docs(query: str, framework: str | None = None, limit: int = 5) -> list[dict]:
    """Hybrid semantic + keyword search over documentation."""
    hits = retriever.search(query, framework, limit)
    return _to_hit_dict(hits)

@mcp.tool()
def get_document(framework: str, path: str) -> str:
    """Return full document content by path."""
    return retriever.get_document(framework, path)

@mcp.tool()
def list_sources() -> dict[str, list[str]]:
    """List all available frameworks and documents."""
    return retriever.list_sources()

@app.post("/search")
def search(req: SearchRequest) -> list[dict]:
    hits = retriever.search(req.query, req.framework, req.limit)
    return _to_hit_dict(hits)

@app.get("/sources")
def sources() -> dict[str, list[str]]:
    return retriever.list_sources()

@app.get("/docs/{framework}/{path:path}")
def get_doc(framework: str, path: str) -> str:
    try:
        return retriever.get_document(framework, path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found")

@app.get("/health")
def health() -> dict:
    chroma_ok = retriever.collection_count() >= 0
    lm_ok = True
    try:
        shared_http_client.get(f"{settings.lm_studio_url}/models", headers=settings.lm_studio_headers, timeout=3).raise_for_status()
    except Exception:
        lm_ok = False
    return {
        "chroma": chroma_ok,
        "lm_studio": lm_ok,
        "bm25_loaded": retriever.bm25 is not None,
        "collection_count": retriever.collection_count(),
        "embedding_model": settings.embedding_model,
    }
```

---

## Шаг 7. `Dockerfile`

```dockerfile
FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock .
COPY docs_shared/pyproject.toml docs_shared/

RUN uv sync --frozen

COPY docs_shared/ /app/docs_shared/
COPY ingestion/ /app/ingestion/
COPY app/ /app/app/

RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app
USER app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app"

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
```

### `pyproject.toml` (root workspace)
```toml
[project]
name = "lore"
version = "0.1.0"
requires-python = ">=3.14,<3.15"
dependencies = [
    "chromadb>=0.5.0",
    "rank-bm25>=0.2.2",
    "httpx>=0.27.0",
    "structlog>=24.0.0",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "fastmcp>=2.0.0",
    "markdown-it-py>=3.0.0",
    "docs-shared",
]

[dependency-groups]
dev = ["pytest>=8.0", "ruff>=0.5.0"]

[tool.uv.workspace]
members = ["docs_shared"]

[tool.uv.sources]
docs-shared = { workspace = true }

[tool.hatch.build.targets.wheel]
packages = ["."]
```

---

## Порядок запуска

```bash
cd /Users/mvl/code/lore

# 1. Скопировать и заполнить .env
cp .env.example .env
# Заполнить LM_STUDIO_API_KEY (из LM Studio → Settings → Server)

# 2. Сгенерировать lock-файл и установить зависимости
make lock && make install

# 3. Запустить контейнер
make up

# 4. Проверить здоровье
curl http://localhost:8000/health

# 5. Положить документы
cp ~/docs/spark/*.md data/raw/spark/

# 6. Индексировать
make ingest

# 7. Проверить поиск
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "your query"}'
```

---

## Порядок реализации (TODO)

1. [x] Создать структуру директорий
2. [x] Создать `docker-compose.yml`, `.env.example`, `.python-version`, `Makefile`
3. [x] Реализовать `docs_shared/` (config, retriever, guards, __init__)
4. [x] Реализовать `ingestion/` (chunker, embedder, bm25_index, ingest)
5. [x] Реализовать `app/` (единый сервер: FastAPI + FastMCP)
6. [x] Создать `README.md`
7. [x] Добавить аутентификацию LM Studio по API-токену
8. [x] Консолидация: 1 контейнер, PersistentClient, единый Dockerfile
9. [x] HTTP retry (httpx.HTTPTransport(retries=3))
10. [x] Валидация limit (ge=1, le=100)
11. [x] BM25 full rebuild (убран merge)
12. [x] embedding_function=None в коллекциях
13. [x] Structlog JSON-форматтер
14. [x] Fix: volume shadowing в docker-compose.yml
15. [x] Fix: репродуктивные Docker-сборки (uv sync --frozen)
16. [x] Fix: non-root user в Dockerfile
17. [x] Fix: clamp similarity scores (max 0.0)
18. [x] Fix: BM25/Chroma consistency при --framework
19. [x] Fix: unused overlap param, import os, legacy make targets
20. [x] Fix: PYTHONPATH для docs_shared пакета
21. [x] Fix: permissions для bm25.pkl (volume mount ./data:/data)
22. [x] Тестовый документ test.md проиндексирован и ищется
23. [x] Migrate to uv workspace (единый lock, единый .venv)
24. [x] Header-aware chunking: heading chain, is_last_chunk, configurable size/overlap
25. [x] Разделение сырья и подготовленных данных: `data/source/` → `preparers/` → `data/prepared/`
26. [x] Per-framework preparer с общим контрактом `FrameworkPreparer`
27. [x] Атомарная подготовка через staging-tempdir + rename
28. [x] Переписан чанкер: code-aware, atomic code-fence, H4 label merging, heading-chain в embedding
29. [x] Тесты: 25 тестов чанкера + 8 тестов preparer'ов = 33 теста проходят
30. [x] Положить production source-файлы в `data/source/{framework}/` и регенерировать `data/prepared/`
31. [ ] Подключить opencode к MCP endpoint
