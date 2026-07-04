# Testing

## Commands

```bash
make test                                    # all tests
uv run pytest tests/test_chunker.py -v        # chunker only
uv run pytest tests/test_preparer_base.py -v  # preparer contract only
uv run pytest -k "code" -v                    # keyword filter
```

## Coverage

| File | Tests | Coverage |
|------|-------|----------|
| `test_chunker.py` | 25 | Heading chain, H4-labels, code atomicity, prose overlap, `is_last_chunk`, metadata, block parsing |
| `test_preparer_base.py` | 16 | Protocol conformance, atomic rename, dry-run, registry discovery, spark preparer helpers |

## Test Categories

### Chunker Tests (`test_chunker.py`)

- **Heading chain** — H1/H2/H3 chain building, H4/H5/H6 exclusion, chain reset on level change
- **Code blocks** — H4 label attachment, atomic code fences, no overlap across code, `has_code`/`code_languages` metadata
- **Prose splitting** — sentence-based split, overlap, section boundary isolation
- **Metadata** — `is_last_chunk`, sequential indices, title fallback, block types
- **Block parsing** — `_parse_blocks` returns typed blocks, `_build_sections` attaches H4 labels

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
2. Preparer tests: create `_FakePreparer` or use real preparers with `tmp_path` fixtures
3. Use `pytest.fixture` for temporary directories and source files

## Pre-commit Checklist

- [ ] `make test` passes
- [ ] `uv run ruff check` passes
- [ ] If chunking changed: `make ingest-clear && make ingest`
- [ ] If API changed: `curl http://localhost:8000/health` is healthy
