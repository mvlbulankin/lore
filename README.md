# Lore

[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/downloads/release/python-3140/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Локальный RAG-сервер документации с MCP-интерфейсом для агентов.

Один Docker-контейнер: ChromaDB (PersistentClient, in-process) + FastAPI (REST) + FastMCP.

## Архитектура

| Слой | Решение |
|------|---------|
| Vector DB | ChromaDB `PersistentClient` (in-process) |
| Embedding | `nomic-embed-text-v1.5` (768 dims) через LM Studio |
| Retrieval | Hybrid: BM25 + Vector + RRF (k=60) |
| Chunking | Code-aware: H1>H2>H3 chain, atomic code-fence, prose с overlap |
| Container | Один образ ~360MB (python:3.14-slim + uv) |
| Pipeline | `data/source/` → `preparers/` → `data/prepared/` → `ingestion/` → ChromaDB |

## Требования

- **Docker** — для контейнера lore
- **uv** — менеджер пакетов Python
- **LM Studio** — запущен локально с моделью `nomic-embed-text-v1.5`
- **Python 3.14**

## Quick Start

```bash
# 1. Настроить .env
cp .env.example .env
# Заполнить LM_STUDIO_API_KEY

# 2. Подготовить документы
make prepare

# 3. Запустить контейнер
make up

# 4. Проверить здоровье
curl http://localhost:8000/health

# 5. Проиндексировать
make ingest

# 6. Перезапустить контейнер (BM25 загружается при старте)
make down && make up

# 7. Поиск
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "your query", "framework": "spark", "limit": 5}'
```

## Команды

| Команда | Описание |
|---------|----------|
| `make install` | Установка зависимостей |
| `make up` | Запуск контейнера |
| `make down` | Остановка контейнера |
| `make prepare` | Подготовить все фреймворки |
| `make ingest` | Индексация документов |
| `make ingest-clear` | Очистить и заново проиндексировать |
| `make test` | Запуск тестов |
| `make logs` | Логи контейнера |
| `make clean` | Удалить контейнер, volumes, venv |

## Документация

| Файл | Описание |
|------|----------|
| [docs/areas/retriever.md](docs/areas/retriever.md) | HybridRetriever, BM25, ChromaDB, RRF |
| [docs/areas/chunker.md](docs/areas/chunker.md) | Code-aware chunking |
| [docs/areas/preparers.md](docs/areas/preparers.md) | FrameworkPreparer, pipeline |
| [docs/areas/ingestion.md](docs/areas/ingestion.md) | Ingest workflow, embedder |
| [docs/areas/server.md](docs/areas/server.md) | FastAPI, FastMCP, endpoints |
| [docs/architecture.md](docs/architecture.md) | Детальная архитектура |
| [docs/testing.md](docs/testing.md) | Тесты |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Troubleshooting |

## MCP

Добавить в конфигурацию MCP-клиента:

```json
{
  "mcp": {
    "lore": {
      "type": "remote",
      "url": "http://<server-ip>:8000/mcp",
      "enabled": true
    }
  }
}
```

Доступные инструменты: `search_docs`, `get_document`, `list_sources`.
