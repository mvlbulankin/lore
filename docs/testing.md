# Testing

## Commands

```bash
make test                                    # all tests
uv run pytest tests/test_chunker.py -v        # chunker only
uv run pytest tests/test_sparse_builder.py -v # sparse builder only
uv run pytest tests/test_retriever.py -v      # retriever only
uv run pytest -k "parent" -v                  # keyword filter
```

## Coverage

| File | Tests | Coverage |
|------|-------|----------|
| `test_chunker.py` | 35 | Heading chain, H4-labels, code atomicity, prose overlap, `is_last_chunk`, metadata, block parsing, **parent-child chunking** |
| `test_preparer_base.py` | 12 | Protocol conformance, atomic rename, dry-run, registry discovery, spark preparer helpers |
| `test_sparse_builder.py` | 6 | TF-IDF fit/build, encode_query, save/load, error handling |
| `test_retriever.py` | 8 | Qdrant collection, framework filter, prefetch + Fusion.RRF, sparse model, parent dedup, path traversal |

## Test Categories

### Chunker Tests (`test_chunker.py`)

- **Heading chain** — H1/H2/H3 chain building, H4/H5/H6 exclusion, chain reset on level change
- **Code blocks** — H4 label attachment, atomic code fences, no overlap across code, `has_code`/`code_languages` metadata
- **Prose splitting** — sentence-based split, overlap, section boundary isolation
- **Metadata** — `is_last_chunk`, sequential indices, title fallback, block types
- **Block parsing** — `_parse_blocks` returns typed blocks, `_build_sections` attaches H4 labels
- **Parent-child** — `parent_id` format, multi-chunk `parent_content`, `parent_level` parameter, different sections

### Sparse Builder Tests (`test_sparse_builder.py`)

- **fit_build** — returns correct number of SparseVectors with matching indices/values
- **build** — transforms new texts after fitting
- **encode_query** — encodes single query string
- **save/load** — round-trip persistence preserves query encoding
- **Error handling** — build/encode before fit raises RuntimeError

### Retriever Tests (`test_retriever.py`)

- **collection_count** — verifies Qdrant upsert
- **framework_filter** — `MatchValue` filter works correctly
- **prefetch_fusion_rrf** — `Prefetch` + `FusionQuery(fusion=Fusion.RRF)` returns results
- **sparse_model** — save/load round-trip works
- **parent_dedup** — keeps highest-scoring child per parent

### Preparer Tests (`test_preparer_base.py`)

- **Protocol** — `_FakePreparer` satisfies `FrameworkPreparer`
- **Discovery** — returns correct paths
- **Transform** — returns `PreparedDoc` with correct fields
- **Atomic rename** — staging → rename → cleanup, no leftover directories
- **Dry-run** — no files written when `execute=False`
- **Re-execute** — replaces previous output
- **Registry** — discovers all registered preparers, filters by framework
- **Spark helpers** — redirect stub filter, notebook cell cleanup, empty fence cleanup, language default

## Requirements

- Python 3.14
- `pytest` (from `[dependency-groups].dev`)
- `conftest.py` adds project root to `sys.path` for package imports

## Writing New Tests

1. Chunker tests: import from `ingestion.chunker`, use `make_chunks()` with synthetic markdown
2. Sparse builder tests: import from `ingestion.sparse_builder`, use `SparseBuilder()`
3. Retriever tests: use QdrantClient with `path=tempfile.TemporaryDirectory()`
4. Preparer tests: create `_FakePreparer` or use real preparers with `tmp_path` fixtures
5. Use `pytest.fixture` for temporary directories and source files

## Pre-commit Checklist

- [ ] `make test` passes
- [ ] `uv run ruff check` passes
- [ ] If chunking changed: `make ingest-clear && make ingest`
- [ ] If API changed: `curl http://localhost:8000/health` is healthy
