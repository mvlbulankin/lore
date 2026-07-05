# Тесты

```bash
make test                                    # все тесты
uv run pytest tests/test_chunker.py -v        # только чанкер
uv run pytest tests/test_preparer_base.py -v  # только preparer contract
```

## Что покрыто

| Файл | Тестов | Что проверяет |
|---|---|---|
| `test_chunker.py` | 35 | Heading chain, H4-labels, code-блоки атомарны, overlap только для prose, parent-child, `is_last_chunk`, метаданные |
| `test_preparer_base.py` | 12 | `FrameworkPreparer` Protocol, атомарный rename через staging, dry-run без записи, registry discovers per-framework preparers, Spark cleanup helpers |

## Требования

- Python 3.14
- Зависимости из `[dependency-groups].dev` в `pyproject.toml` (`pytest`, `ruff`)
- `preparers/` импортируется как пакет (через `tests/conftest.py` добавляет корень в `sys.path`)