# Тесты

```bash
make test                              # все тесты
uv run pytest tests/test_chunker.py -v  # только чанкер
```

## Что покрыто

| Файл | Тестов | Что проверяет |
|---|---|---|
| `test_chunker.py` | 35 | Heading chain, H4-labels, code-блоки атомарны, overlap только для prose, parent-child, `is_last_chunk`, метаданные |

## Требования

- Python 3.14
- Зависимости из `[dependency-groups].dev` в `pyproject.toml` (`pytest`, `ruff`)
