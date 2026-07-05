# Lore

[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/downloads/release/python-3140/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Локальный RAG-сервер документации с MCP-интерфейсом для агентов.

Один Docker-контейнер: Qdrant (embedded, in-process) + FastAPI (REST) + FastMCP + fastembed-gpu (ONNX).

## Архитектура

| Слой | Решение |
|------|---------|
| Vector DB | Qdrant embedded `AsyncQdrantClient` (in-process) |
| Embedding | `BAAI/bge-small-en-v1.5` (384 dims) через fastembed-gpu (ONNX, CUDA) |
| Retrieval | Hybrid: TF-IDF sparse + dense embeddings + RRF (server-side via Qdrant prefetch + FusionQuery) |
| Chunking | Code-aware: H1>H2>H3 chain, atomic code-fence, prose с overlap |
| Container | Один образ ~400MB (python:3.14-slim + uv) |
| Pipeline | `data/source/` → `preparers/` → `data/prepared/` → `ingestion/` → Qdrant |

## Требования

- **Docker** — для контейнера lore
- **uv** — менеджер пакетов Python
- **nvidia-container-toolkit** — для GPU-ускорения ONNX
- **NVIDIA GPU + драйвер** — CUDA 12/13 совместимый
- **Python 3.14**

## Quick Start

```bash
# 1. Настроить .env
cp .env.example .env

# 2. Подготовить документы
make prepare

# 3. Запустить контейнер
make up

# 4. Проверить здоровье
curl http://localhost:8000/health

# 5. Проиндексировать
make ingest

# 6. Поиск
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
| [docs/areas/retriever.md](docs/areas/retriever.md) | QdrantRetriever, TF-IDF sparse, Qdrant, RRF |
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
