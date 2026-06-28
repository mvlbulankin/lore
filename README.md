# Lore

Локальный RAG-сервер документации с MCP-интерфейсом для агентов (opencode).

Один Docker-контейнер: ChromaDB (PersistentClient, in-process) + FastAPI (REST) + FastMCP.

## Архитектура

| Слой | Решение |
|------|---------|
| Vector DB | ChromaDB `PersistentClient` (in-process) |
| Embedding | `nomic-embed-text-v1.5` (768 dims) через LM Studio |
| Retrieval | Hybrid: BM25 + Vector + RRF (k=60) |
| BM25 | `data/bm25.pkl`, full rebuild при каждом ingest |
| Chunking | Code-aware: H1>H2>H3 chain, H4 labels, code-fence atomic, prose с sentence-overlap |
| MCP SDK | FastMCP, mounted в FastAPI на `/mcp` |
| API | FastAPI (REST), uvicorn |
| HTTP client | httpx с retry (3 retries) |
| Container | Один образ ~360MB (python:3.12-slim + uv) |
| Pipeline | `data/source/` → `preparers/` → `data/prepared/` → `ingestion/` → ChromaDB |

## Требования

- **Docker** — для контейнера lore
- **uv** — менеджер пакетов Python (для локальной разработки и подготовки документации)
- **LM Studio** — запущен локально с моделью `nomic-embed-text-v1.5`
- **Python 3.12**

---

## Пошаговый запуск

Pipeline состоит из трёх этапов:

```
data/source/  ──►  preparers/  ──►  data/prepared/  ──►  ingestion  ──►  ChromaDB + BM25
   (сырьё)       (host, uv)        (готовые .md)       (docker)        (для поиска)
```

### Шаг 1. Настройка `.env`

```bash
cp .env.example .env
```

Открыть `.env` и заполнить переменные (см. таблицу ниже).

### Шаг 2. Настройка LM Studio

1. Открыть LM Studio
2. Перейти в **Settings → Server**
3. Включить **API Authentication** (если ещё не включено)
4. Скопировать API-токен
5. Вставить токен в `.env` → переменная `LM_STUDIO_API_KEY`
6. Убедиться, что модель `nomic-embed-text-v1.5` загружена
7. Убедиться, что локальный сервер запущен на порту `1234`

### Шаг 3. Установка зависимостей (опционально, для dev)

```bash
make install
```

Выполняет `uv sync` в корне workspace (для локальных тестов).

### Шаг 4. Подготовка документации

> Тестовые документы уже доступны в `data/source/test/test.md`. Для production-документации положите сырьё в `data/source/{framework}/` (например, Jekyll-исходники Spark в `data/source/spark/docs/`, MDX-исходники Delta в `data/source/delta/docs/src/content/docs/`).

```bash
# Посмотреть что будет сделано
make prepare-dry-run

# Подготовить все фреймворки (читает data/source/, пишет в data/prepared/)
make prepare

# Подготовить только один фреймворк
make prepare-spark
make prepare-delta
```

Каждый preparer работает атомарно через staging-tempdir + rename. Это гарантирует, что `make ingest` всегда читает консистентный snapshot `data/prepared/{framework}/`.

### Шаг 5. Запуск

```bash
make up
```

Запускает один контейнер `lore` (порт 8000).

### Шаг 6. Проверка здоровья

```bash
curl http://localhost:8000/health
```

Ожидаемый ответ:
```json
{
  "chroma": true,
  "lm_studio": true,
  "bm25_loaded": false,
  "collection_count": 0,
  "embedding_model": "nomic-embed-text-v1.5"
}
```

`bm25_loaded: false` и `collection_count: 0` нормально — индекс ещё не создан. После `make ingest` оба будут заполнены.

### Шаг 7. Индексация

```bash
make ingest
```

Контейнер `lore`:
1. Сканирует все `.md` файлы в `data/prepared/{framework}/`
2. Парсит структуру markdown (H1 → H2 → H3)
3. Разбивает на чанки по секциям с overlap (настроено через `CHUNK_MAX_WORDS`, `CHUNK_OVERLAP_WORDS`)
4. Code-fence'ы сохраняются атомарно (никогда не делятся посередине)
5. H4-лейблы перед code-блоками приклеиваются к ним как language labels
6. Heading chain (`"H1 > H2 > H3"`) добавляется в embedding-контент
7. Сохраняет `is_last_chunk`, `has_code`, `code_languages`, `block_types` в metadata
8. Получает эмбеддинги через LM Studio
9. Записывает в ChromaDB (PersistentClient)
10. Строит BM25-индекс (full rebuild)

### Шаг 8. Тестирование поиска

Через REST API:
```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "your search query", "framework": "spark", "limit": 5}'
```

Через MCP (после подключения opencode, см. ниже):
- Tool `search_docs(query, framework?, limit?)`
- Tool `get_document(framework, path)`
- Tool `list_sources()`

---

## Переменные `.env`

| Переменная | Описание | Пример | Обязательно |
|---|---|---|---|
| `LM_STUDIO_URL` | URL локального LM Studio API | `http://host.docker.internal:1234/v1` | Да |
| `LM_STUDIO_API_KEY` | API-токен LM Studio (Bearer) | `sk-xxxxxxxx` | Да |
| `EMBEDDING_MODEL` | Название модели эмбеддингов | `nomic-embed-text-v1.5` | Да |
| `CHROMA_PERSIST_DIR` | Путь к хранилищу ChromaDB | `/data/chroma` | Да |
| `CHROMA_COLLECTION` | Имя коллекции в ChromaDB | `docs` | Да |
| `RRF_K` | Параметр RRF-фьюжн для ранжирования | `60` | Да |
| `PREPARED_DIR` | Путь к подготовленным `.md` (монтируется в контейнер) | `/data/prepared` | Да |
| `BM25_PATH` | Путь к файлу BM25-индекса | `/data/bm25.pkl` | Да |
| `SERVER_PORT` | Порт сервера внутри контейнера | `8000` | Да |
| `CHUNK_MAX_WORDS` | Максимальный размер чанка (слов) | `800` | Да |
| `CHUNK_OVERLAP_WORDS` | Overlap между соседними prose-чанками | `80` | Да |

### Описание переменных

- **`LM_STUDIO_URL`** — URL, по которому доступен LM Studio из Docker-контейнера. `host.docker.internal` разрешается в IP хост-машины.

- **`LM_STUDIO_API_KEY`** — API-токен для аутентификации запросов к LM Studio.

- **`EMBEDDING_MODEL`** — название модели, используемой для генерации эмбеддингов. Должно совпадать с моделью, загруженной в LM Studio. При смене модели нужно выполнить `make ingest-clear`.

- **`CHROMA_PERSIST_DIR`** — путь внутри контейнера к директории ChromaDB PersistentClient. Монтируется из `data/chroma/`.

- **`CHROMA_COLLECTION`** — имя коллекции в ChromaDB.

- **`RRF_K`** — параметр Reciprocal Rank Fusion для фьюжн-ранжирования.

- **`PREPARED_DIR`** — путь внутри контейнера к подготовленным `.md`. Монтируется из `data/prepared/`. Подготовка делается на хосте через `make prepare`.

- **`BM25_PATH`** — путь внутри контейнера к файлу BM25-индекса.

- **`SERVER_PORT`** — порт uvicorn внутри контейнера.

- **`CHUNK_MAX_WORDS`** — максимальное количество слов в одном чанке. Code-fence'ы могут превышать (они атомарны).

- **`CHUNK_OVERLAP_WORDS`** — количество слов overlap между соседними prose-чанками. Не применяется к code-блокам.

---

## REST API

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/search` | Гибридный поиск (BM25 + Vector) |
| `GET` | `/sources` | Список всех фреймворков и документов |
| `GET` | `/docs/{framework}/{path}` | Получить полный документ |
| `GET` | `/health` | Проверка здоровья сервисов |

### `POST /search`

Body:
```json
{
  "query": "your search query",
  "framework": "spark",
  "limit": 5
}
```

`framework` и `limit` опциональны. `limit` ограничен диапазоном 1–100.

Ответ содержит поле `heading` — цепочка заголовков секции (например `"Best practices > Compact files"`), включена в embedding-контент каждого чанка.

---

## Подключение opencode

Добавить в `~/.config/opencode/opencode.json`:

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

Заменить `<server-ip>` на IP машины, где запущен сервер. Для локальной разработки: `localhost`.

---

## Команды

| Команда | Описание |
|---|---|
| `make install` | Установка зависимостей (`uv sync`) |
| `make lock` | Генерация lock-файла (`uv lock`) |
| `make up` | Запуск контейнера lore |
| `make down` | Остановка контейнера |
| `make prepare-dry-run` | Показать что будет сделано (без записи) |
| `make prepare` | Подготовить все фреймворки (data/source → data/prepared) |
| `make prepare-spark` | Подготовить только Spark |
| `make prepare-delta` | Подготовить только Delta |
| `make ingest` | Индексация документов (full rebuild BM25 + ChromaDB) |
| `make ingest-clear` | Очистить коллекцию → заново проиндексировать |
| `make logs` | Лог контейнера в реальном времени |
| `make test` | Запуск тестов |
| `make clean` | Удалить контейнер, volumes, venv |

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
├── pyproject.toml              # workspace root + все deps
├── uv.lock                     # единый lock-файл
├── data/
│   ├── source/                 # сырьё (Jekyll, MDX, Python) — read-only
│   │   ├── spark/docs/
│   │   ├── delta/docs/
│   │   ├── delta/examples/
│   │   └── test/
│   ├── prepared/               # выход preparers (готовые .md)
│   │   ├── spark/
│   │   ├── delta/
│   │   └── test/
│   ├── chroma/                 # ChromaDB persistent storage
│   └── bm25.pkl                # BM25 index (generated)
├── docs_shared/                # общий пакет (workspace member)
│   ├── pyproject.toml
│   ├── config.py               # Settings (PREPARED_DIR)
│   ├── retriever.py            # HybridRetriever
│   └── guards.py
├── preparers/                  # подготовка документации (на хосте, через uv)
│   ├── base.py                 # FrameworkPreparer Protocol
│   ├── registry.py             # автодискавери preparer'ов
│   ├── cli.py                  # python -m preparers.cli
│   ├── _atomic.py              # staging + atomic rename
│   ├── delta/
│   │   ├── README.md
│   │   └── prepare.py          # MDX → MD, Python → MD
│   ├── spark/
│   │   ├── README.md
│   │   └── prepare.py          # Jekyll cleanup + PySpark HTML download
│   └── test/
│       └── prepare.py          # trivial copy
├── ingestion/                  # индексация (запускается в контейнере)
│   ├── chunker.py              # code-aware markdown chunker
│   ├── embedder.py
│   ├── bm25_index.py
│   └── ingest.py
├── app/                        # единый сервер (MCP + REST)
│   └── server.py
└── tests/
    ├── conftest.py
    ├── test_chunker.py         # 25 тестов
    └── test_preparer_base.py   # 8 тестов
```

---

## Troubleshooting

### `lm_studio: false` в `/health`

1. Убедиться, что LM Studio запущен и локальный сервер активен
2. Проверить `LM_STUDIO_API_KEY` в `.env` — токен должен быть верным
3. Проверить `LM_STUDIO_URL` — порт должен совпадать с настройками LM Studio
4. Проверить вручную: `curl -H "Authorization: Bearer <token>" http://localhost:1234/v1/models`

### ChromaDB не отвечает

1. `docker compose logs lore` — ищите ошибки при инициализации
2. `collection_count` в `/health` — если > 0, ChromaDB работает
3. Права доступа к `data/chroma/` — контейнер должен иметь write-доступ

### Embed drift warning в логах

Сообщение `embedding_model_mismatch` означает, что модель эмбеддингов сменилась, но в ChromaDB остались старые векторы. Решение:

```bash
make ingest-clear
```

### Пустые результаты поиска

1. Убедиться, что `data/prepared/{framework}/` содержит `.md` файлы
2. Убедиться, что документы проиндексированы: `make ingest`
3. Проверить `bm25_loaded: true` в `/health`
4. Проверить список источников: `curl http://localhost:8000/sources`

### Подготовка не находит source-файлы

Убедиться, что файлы лежат в `data/source/{framework}/` в формате, который знает preparer. Для Spark это `data/source/spark/docs/*.md`, для Delta — `data/source/delta/docs/src/content/docs/*.mdx` + `data/source/delta/examples/python/*.py`.

### После обновления chunking — старые индексы несовместимы

Новый chunker добавляет `heading` в контент и `has_code`/`code_languages`/`block_types` в metadata. После обновления кода обязательно выполнить:

```bash
make ingest-clear && make ingest
```

### Ошибка подключения из Docker к LM Studio

`host.docker.internal` должен разрешаться в IP хост-машины. Если не работает:
- Проверить: `docker run --rm alpine nslookup host.docker.internal`
- Заменить на IP адрес хост-машины в `LM_STUDIO_URL`

### BM25 rebuild при частичном ingest

BM25-индекс всегда rebuild'ится полностью при каждом `make ingest`, даже если указан `--framework`. Это гарантирует консистентность между BM25 и ChromaDB.

### Поиск возвращает 0 hits после `make ingest`

`HybridRetriever` загружает `bm25.pkl` при старте контейнера. После `make ingest` нужно перезапустить контейнер чтобы retriever подхватил новый индекс:

```bash
make down && make up
```

### `ModuleNotFoundError: No module named 'docs_shared'` при ingest

Контейнер запускается от non-root пользователя, а пакет `docs_shared` лежит в `/app`. Убедитесь, что `PYTHONPATH=/app` указан в `Dockerfile` и передаётся в Makefile-целях (`sh -c 'PYTHONPATH=/app ...'`).

### Поиск возвращает 0 hits после `make ingest`

`HybridRetriever` загружает `bm25.pkl` при старте контейнера. После `make ingest` нужно перезапустить контейнер чтобы retriever подхватил новый индекс:

```bash
make down && make up
```

### Подготовка: "directory not found"

Убедиться, что `data/source/{framework}/` существует. Если source был перенесён, проверьте путь через `make prepare-dry-run`.