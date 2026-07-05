# Plan: Code Quality and Architecture Fixes

## Context

Comprehensive audit (2026-07-05) of the Lore project identified 14 issues
across four categories: **security** (path traversal, pickle), **architecture**
(global state, encapsulation), **code quality** (dead code, magic numbers,
duplication), and **documentation drift** (outdated AGENTS.md, untested
coverage). Compliance with FastAPI / FastMCP / Qdrant best practices was
verified against current documentation via context7 — the project follows
them correctly; the issues are project-specific.

**Goal**: fix all identified issues without breaking existing functionality
or test coverage. Each fix is independent and testable.

## Confirmed decisions

| Question | Decision |
|---|---|
| Path traversal fix | Resolve + check `is_relative_to(prepared_dir)` |
| Global state in `server.py` | Factory pattern + lazy init via lifespan |
| `docs_shared/http_client.py` | Remove (dead code post-LM-Studio-migration) |
| `gc.collect()` calls | Keep in critical paths only, document why |
| Test refactor | Extract ingest pipeline helper |
| Coverage tracking | Add `pytest-cov` to dev deps |
| `Hit.id` type | `int \| str` (Qdrant returns int, we str-convert) |
| Embedding-dim validation | `model_validator` checks dim matches model |

---

## Phase A — Critical: Path traversal (security)

**Goal**: block `/docs/spark/../../etc/passwd` style attacks. **5 min, do first.**

### A.1 Fix in `docs_shared/retriever.py:161-166`

**Current (vulnerable)**:
```python
def get_document(self, framework: str, path: str) -> str:
    p = Path(settings.prepared_dir) / framework / path
    if not p.exists():
        raise DocumentNotFoundError(f"Document not found: {p}")
    return p.read_text(encoding="utf-8")
```

**Fixed**:
```python
def get_document(self, framework: str, path: str) -> str:
    base = Path(settings.prepared_dir).resolve()
    p = (base / framework / path).resolve()
    if not p.is_relative_to(base):
        raise DocumentNotFoundError(f"Document not found: {path}")
    if not p.is_file():
        raise DocumentNotFoundError(f"Document not found: {path}")
    return p.read_text(encoding="utf-8")
```

**Tests to add** (`tests/test_retriever.py`):
- `test_get_document_blocks_path_traversal` — `/docs/spark/../etc/passwd` raises `DocumentNotFoundError`
- `test_get_document_blocks_absolute_path` — `/docs/spark//etc/passwd` blocked
- `test_get_document_returns_real_file` — happy path still works

**Acceptance**: 3 new tests pass; existing retriever tests unaffected.

---

## Phase B — Architecture: global state in server.py

**Goal**: remove module-level `embedder` and `retriever` globals; use lifespan
for initialization. **30 min.**

### B.1 Replace globals with app-state pattern in `app/server.py`

**Current (problematic)**:
```python
embedder = Embedder(cache_dir="/data/fastembed_cache")
retriever = QdrantRetriever(embedder=embedder)

mcp = FastMCP("lore")
mcp_app = mcp.http_app(path="/")

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    if not retriever.verify_embedding_model():
        log.error("embedding_model_drift_detected", hint="run: make ingest-clear")
    yield
    await retriever.aclose()
```

**Refactored (factory + app.state)**:
```python
@asynccontextmanager
async def app_lifespan(app: FastAPI):
    embedder = Embedder(cache_dir="/data/fastembed_cache")
    retriever = QdrantRetriever(embedder=embedder)
    app.state.embedder = embedder
    app.state.retriever = retriever
    try:
        if not retriever.verify_embedding_model():
            log.error("embedding_model_drift_detected", hint="run: make ingest-clear")
        yield
    finally:
        await retriever.aclose()

app = FastAPI(
    title="Docs API",
    lifespan=combine_lifespans(app_lifespan, mcp_app.lifespan),
)
app.mount("/mcp", mcp_app)


def get_retriever(request: Request) -> QdrantRetriever:
    return request.app.state.retriever


# All endpoints and MCP tools use Depends(get_retriever) or via context
```

**Update endpoints** (`app/server.py:75-138`):
- Each `await retriever.search(...)` → `await get_retriever(request).search(...)` for REST
- Each `mcp.tool()` accesses retriever via `Context` (FastMCP 2.x) or via module-level wrapper

**Update tests** (`tests/test_server.py:84-86, 152-154, 176-178, 200-203, 230, 247-249`):
- Replace `patch("app.server.retriever", ...)` with `patch("app.server._get_retriever", ...)` or test client with dependency override

**Acceptance**: 107+ tests pass; `make test` clean; `make up` works end-to-end; health-check returns same shape.

---

## Phase C — Code quality cleanup

**Goal**: remove dead code, fix lazy import, unify logging, eliminate magic numbers.

### C.1 Remove `docs_shared/http_client.py` (dead code)

**Action**: delete file. The `httpx` usage in `preparers/spark/prepare.py:20` is direct (raw `httpx.Client`) and works fine.

**Verify**: `grep -r "from docs_shared.http_client\|docs_shared.http_client" --include="*.py" .` should return nothing after deletion.

### C.2 Move `from fastembed import TextEmbedding` to top of `docs_shared/embedder.py:25`

**Current (lazy in `__init__`)**:
```python
def __init__(self, ...):
    from fastembed import TextEmbedding
    ...
```

**Fixed (top-level)**:
```python
from fastembed import TextEmbedding
```

**Update tests** (`tests/test_embedder_local.py:20, 28, 37, 44, 55, 64, 72, 82, 89, 108, 115, 128, 137, 145, 154` and `tests/conftest.py:42-58`):
- `patch("fastembed.TextEmbedding")` → `patch("docs_shared.embedder.TextEmbedding")`
- `conftest.py` mock injection stays (still needed for `import onnxruntime` blocking)

**Acceptance**: 12 embedder tests pass; conftest still injects mock for other tests.

### C.3 Unify structlog configuration in `docs_shared/logging.py`

**New file** `docs_shared/logging.py`:
```python
"""Shared structlog configuration for server and ingest."""
from __future__ import annotations

import structlog


def configure_logging(level: str = "INFO") -> None:
    structlog.configure(
        cache_logger_on_first_use=True,
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
    )
```

**Update**:
- `app/server.py:17-27` → `from docs_shared.logging import configure_logging` + `configure_logging()`
- `ingestion/ingest.py:82-92` → same

**Acceptance**: structlog output identical (JSON, INFO level) in both server and ingest; tests pass.

### C.4 Reduce `gc.collect()` calls in `ingestion/ingest.py`

**Current (aggressive)**: `gc.collect()` after every file (line 123), after `del all_texts` (line 133), after per-framework `del` (line 199, 213, 232, 255, 259, 277). **7 calls per ingest run.**

**Action**:
- Keep `gc.collect()` only after **major memory releases**:
  - After `del all_texts` (line 133) — was ~1.5GB
  - After `del embedder` in `finally` (line 275)
- Remove from per-file and per-framework loops — CPython refcounting handles short-lived objects

**Acceptance**: ingest completes in same or less time; memory profile similar (peak); no OOM regression.

### C.5 Make magic numbers configurable (env vars)

**New settings** (`docs_shared/config.py`):
```python
class Settings(BaseSettings):
    ...
    snippet_max_chars: int = Field(default=500, gt=0)
    parent_content_max_chars: int = Field(default=2000, gt=0)
    ingest_batch_size: int = Field(default=256, gt=0)
    search_fetch_multiplier: int = Field(default=4, gt=0)
    search_fetch_min: int = Field(default=20, gt=0)
```

**Update**:
- `app/server.py:32-33` → use `settings.snippet_max_chars`, `settings.parent_content_max_chars`
- `ingestion/ingest.py:216` → use `settings.ingest_batch_size`
- `docs_shared/retriever.py:90` → use `settings.search_fetch_multiplier`, `settings.search_fetch_min`

**.env.example**: add the four new env vars with defaults documented.

**Acceptance**: tests pass; new env vars appear in `.env.example`; existing behavior unchanged with default values.

---

## Phase D — Type safety and validation

**Goal**: fix type hints and add Pydantic validation for embedding-dim consistency.

### D.1 Fix `Hit.id` type in `docs_shared/retriever.py:34`

**Current**:
```python
@dataclass
class Hit:
    id: str  # but Qdrant returns int
```

**Fixed**:
```python
@dataclass
class Hit:
    id: int | str  # Qdrant point IDs can be int or UUID
```

**Update** `docs_shared/retriever.py:147`:
```python
hits.append(Hit(
    id=point.id,  # was: id=str(point.id)
    ...
))
```

### D.2 Add embedding-dim validation in `docs_shared/config.py`

**Add to `Settings`**:
```python
from pydantic import model_validator

KNOWN_MODEL_DIMS = {
    "BAAI/bge-small-en-v1.5": 384,
    "BAAI/bge-base-en-v1.5": 768,
    "nomic-ai/nomic-embed-text-v1.5": 768,
    "BAAI/bge-large-en-v1.5": 1024,
}

class Settings(BaseSettings):
    ...
    @model_validator(mode="after")
    def _validate_dim(self) -> Settings:
        expected = KNOWN_MODEL_DIMS.get(self.embedding_model)
        if expected and self.embedding_dim != expected:
            raise ValueError(
                f"embedding_dim={self.embedding_dim} does not match "
                f"known dim {expected} for model {self.embedding_model}"
            )
        return self
```

**Acceptance**: setting `EMBEDDING_MODEL=nomic-embed` with `EMBEDDING_DIM=384` raises at startup (fast feedback); tests pass with valid configs.

### D.3 Public API for `sparse_builder` in `retriever.py`

**Current (private access)**: `app/server.py:132` — `retriever._sparse_builder is not None`

**Fixed**: add public method in `QdrantRetriever`:
```python
def is_sparse_model_loaded(self) -> bool:
    return self._sparse_builder is not None
```

**Update** `app/server.py:132`:
```python
sparse_ok = retriever.is_sparse_model_loaded()
```

**Acceptance**: `tests/test_server.py:248` updated; 9 server tests pass.

---

## Phase E — Test improvements

**Goal**: add coverage tracking, reduce duplication in integration test.

### E.1 Add `pytest-cov` to dev dependencies

**`pyproject.toml:21`**:
```toml
[dependency-groups]
dev = ["pytest>=8.0", "pytest-cov>=5.0", "pytest-asyncio>=0.23", "ruff>=0.5.0"]
```

**`pyproject.toml:33`** (add `[tool.coverage.*]`):
```toml
[tool.coverage.run]
branch = true
source = ["app", "docs_shared", "ingestion", "preparers"]

[tool.coverage.report]
show_missing = true
fail_under = 70
```

**Makefile** (`make test` line 42-43):
```makefile
test:
	uv run pytest --cov=app --cov=docs_shared --cov=ingestion --cov=preparers --cov-report=term-missing
```

**Acceptance**: `make test` shows coverage; threshold 70% enforced; new tests increase it.

### E.2 Refactor `tests/test_integration.py:120-198, 222-269, 308-358`

**Current (duplicated)**: each test re-implements the full ingest pipeline (chunk → embed → sparse → upsert) inline.

**Refactor**: extract to a helper at top of file or in `tests/conftest.py`:
```python
def _ingest_test_corpus(prepared_dir: Path, qdrant_path: Path, embedding_dim: int = 16) -> None:
    """Ingest a test corpus into a temp Qdrant path with mock embeddings."""
    files = discover_files(prepared_dir, None)
    chunks = []
    for fw, rel in files:
        text = (prepared_dir / fw / rel).read_text(encoding="utf-8")
        chunks.extend(make_chunks(fw, rel, text))

    embeddings = [[0.1] * embedding_dim for _ in chunks]
    sparse_builder = SparseBuilder()
    sparse_vectors = sparse_builder.fit_build([c.content for c in chunks])
    # ... upsert ...
```

**Acceptance**: 3 integration tests still pass, file is ~30% shorter.

### E.3 Add new tests

**For Phase A path traversal** (3 tests in `test_retriever.py`).
**For Phase B lifespan** (1 test: server starts/stops cleanly with lifespan).
**For Phase D.2 dim validation** (1 test: bad dim raises on `Settings()`).

**Acceptance**: 14+ new tests, all pass.

---

## Phase F — Documentation updates

**Goal**: sync `AGENTS.md` with reality.

### F.1 Update `AGENTS.md`

**Changes**:
- Line 7: "fastembed (ONNX, CPU)" → "fastembed-gpu (ONNX, GPU via CUDAExecutionProvider)"
- Line 16: `docs_shared/embedder.py             # fastembed ONNX embedder (in-process)` → `# fastembed-gpu embedder (CUDA required)`
- Line 54: `test_embedder_local.py  # 6 tests` → `# 12 tests`
- Line 100-101: default model + dim:
  ```
  | `EMBEDDING_MODEL` | Embedding model name | `BAAI/bge-small-en-v1.5` |
  | `EMBEDDING_DIM` | Embedding vector dimension | `384` |
  ```
- Line 108: add `EMBEDDING_PROVIDERS` row (default `CUDAExecutionProvider`)
- Line 114-115: Key Design Decisions — add:
  - **GPU-only by default** — hard-fail if CUDA absent
  - **Multi-stage Dockerfile** — CUDA Runtime + cuDNN 9 via COPY from nvidia/cuda image
- Line 124: `/search` body example uses `query, framework?, limit` — still correct
- Line 128-134: REST endpoints — add `/mcp` mount point
- Line 137-144: MCP Tools — note FastMCP 2.x
- Add new "Security" section: pickle used only for self-generated cache, path traversal blocked in `get_document`

### F.2 Update `docs/areas/docker.md` (if outdated)

**Verify and update** any references to CPU fastembed, nomic-embed, image size.

### F.3 Update `docs/areas/ingestion.md` (if outdated)

**Verify and update** any CPU/GPU references, batch_size.

### F.4 Document pickle security model

**New section in `docs/areas/ingestion.md`**:
> **Security note**: `pickle` is used in `ingestion/ingest.py:117` to write
> the chunks cache. The cache is regenerated every ingest run from
> trusted chunking output — never from untrusted input. If the cache
> directory is ever shared with a multi-user system, replace `pickle`
> with `json` (chunk content is JSON-serializable after dataclass
> conversion).

**Acceptance**: AGENTS.md matches current state; all 3 doc files reviewed and updated.

---

## Phase G — Minor improvements

**Goal**: low-effort improvements (CORS, `_HEADING_CHAIN_MAX` parameter, etc.)

### G.1 Add CORS middleware to `app/server.py`

**After** `app = FastAPI(...)`:
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: restrict in production
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
```

**Acceptance**: `curl -H "Origin: http://localhost" -H "Access-Control-Request-Method: GET" -X OPTIONS http://localhost:8000/health` returns 200 with CORS headers.

### G.2 Add `_HEADING_CHAIN_MAX` parameter to `make_chunks`

**`ingestion/chunker.py:80, 189`**: change hardcoded `3` to a parameter:
```python
def make_chunks(
    ...,
    heading_chain_max: int = 3,
) -> list[Chunk]:
    ...
    # line 189: if block.level <= heading_chain_max:
```

**Update** `ingestion/ingest.py:71` and `ingestion/__init__.py` accordingly.

**Acceptance**: existing tests pass; new test `test_heading_chain_max_parameter` verifies behavior.

### G.3 Use `float` consistently for `chunk_index`

**`ingestion/chunker.py:30`** — `chunk_index: int` — but what if we want to identify by string? **Keep as is** (int is correct).

### G.4 Update `Makefile` to use `uv run`

**Verify all `make` targets work with current `uv` versions** (some use `python -m`).

### G.5 Add type hints to `Makefile` `prepare-spark` and `prepare-delta` (already covered by general `prepare`)

Skip — already covered.

### G.6 Move `_KEEP_PATTERNS_PATH` to module-level `_KEEP_PATTERNS`

**`preparers/spark/prepare.py:31-34`** is already at module-level. **No change needed.**

---

## Verify (full cycle)

```bash
# After all phases
make test           # should show 121+ tests, coverage >70%
uv run ruff check   # clean
make rebuild && make up
curl -s http://localhost:8000/health
# {"qdrant":true,"sparse_model":true,"collection_count":3751,"embedding_model":"BAAI/bge-small-en-v1.5"}

# Security smoke test
curl -s http://localhost:8000/docs/spark/../etc/passwd
# Should return 404 (or 500 with DocumentNotFoundError)

# CORS smoke test
curl -sI -H "Origin: http://test" -X OPTIONS http://localhost:8000/search
# Should include Access-Control-Allow-Origin

# Re-run ingest (Phase A.4 — gc.collect() changes)
time make ingest-clear
# Should be similar or faster than before
```

## Acceptance criteria (per phase)

| Phase | Criterion | How to verify |
|-------|-----------|---------------|
| A | 3 new path-traversal tests pass | `pytest tests/test_retriever.py` |
| B | Server still works; no `retriever` global; tests pass | `make test` + `make up` + `/health` |
| C.1 | `http_client.py` removed; no import errors | `grep -r "http_client" --include="*.py" .` empty |
| C.2 | Lazy import removed; embedder tests pass | `pytest tests/test_embedder_local.py` |
| C.3 | One structlog config; no duplication | `grep -A5 "structlog.configure" app/server.py` |
| C.4 | Ingest time not regressed; no OOM | `time make ingest-clear` |
| C.5 | 4 new env vars documented and used | `.env.example` + `Settings(...)` |
| D.1 | `Hit.id: int \| str`; tests pass | `pytest` |
| D.2 | Bad dim raises at startup | `pytest` + manual `Settings(embedding_model="nomic", embedding_dim=384)` |
| D.3 | `is_sparse_model_loaded()` public | `tests/test_server.py:248` updated |
| E.1 | `make test` shows coverage % | `make test` output |
| E.2 | `test_integration.py` ~30% shorter | `wc -l tests/test_integration.py` |
| E.3 | 14+ new tests | `pytest --collect-only` |
| F | `AGENTS.md` matches reality | manual review |
| G.1 | CORS headers in OPTIONS response | `curl -X OPTIONS` |
| G.2 | `heading_chain_max` parameter works | new test |

## Risk

| Risk | Mitigation |
|------|------------|
| Phase B (global state removal) breaks tests | Refactor + run tests after each endpoint |
| `gc.collect()` removal triggers OOM on large corpus | Run full ingest after change; keep memory profiling |
| `model_validator` rejects valid configs | Whitelist `KNOWN_MODEL_DIMS` to common models only |
| CORS too permissive (`*`) | Document with TODO; restrict via env in production |

## Out of scope

- Performance optimization beyond `gc.collect()` review
- Multi-tenancy, authentication, rate limiting
- Migrate `ingest.py` to async (current sync is fine for CLI)
- Replace TF-IDF with GPU-accelerated sparse vectors
- Add metrics (Prometheus, OpenTelemetry)

## Execution checklist

```
[ ] Phase A — Path traversal (security)
    [ ] A.1 Update retriever.py:163-166
    [ ] A.2 Add 3 tests in test_retriever.py
    [ ] make test

[ ] Phase B — Remove global state
    [ ] B.1 Refactor server.py to use lifespan + app.state
    [ ] B.2 Update all endpoints (5 endpoints + 3 MCP tools)
    [ ] B.3 Update test_server.py mock pattern
    [ ] make test, make up, curl /health

[ ] Phase C — Code quality
    [ ] C.1 Delete docs_shared/http_client.py
    [ ] C.2 Move TextEmbedding import to top of embedder.py
    [ ] C.3 Create docs_shared/logging.py
    [ ] C.4 Reduce gc.collect() in ingest.py
    [ ] C.5 Add 4 env vars (Settings + .env.example)
    [ ] make test

[ ] Phase D — Type safety
    [ ] D.1 Fix Hit.id type
    [ ] D.2 Add model_validator for dim
    [ ] D.3 Add is_sparse_model_loaded() public method
    [ ] make test

[ ] Phase E — Tests
    [ ] E.1 Add pytest-cov to dev deps, update Makefile
    [ ] E.2 Refactor test_integration.py (extract helper)
    [ ] E.3 Add 14+ new tests
    [ ] make test (coverage report visible)

[ ] Phase F — Docs
    [ ] F.1 Update AGENTS.md
    [ ] F.2 Review docs/areas/docker.md
    [ ] F.3 Review docs/areas/ingestion.md
    [ ] F.4 Add pickle security note

[ ] Phase G — Minor
    [ ] G.1 Add CORS middleware
    [ ] G.2 heading_chain_max parameter
    [ ] make test, make up, smoke test CORS

[ ] Final verify
    [ ] make test (all 121+ pass, coverage ≥70%)
    [ ] uv run ruff check (clean)
    [ ] make rebuild && make up
    [ ] curl /health, curl /search
    [ ] time make ingest-clear (no regression)
```
