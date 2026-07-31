# Tests

```bash
make test                              # all tests
uv run pytest tests/test_chunker.py -v  # chunker only
```

## Coverage

| File | Tests | Covers |
|---|---|---|
| `test_chunker.py` | 35 | Heading chain, H4-labels, code blocks are atomic, overlap for prose only, parent-child, `is_last_chunk`, metadata |

## Requirements

- Python 3.14
- Dependencies from `[dependency-groups].dev` in `pyproject.toml` (`pytest`, `ruff`)
