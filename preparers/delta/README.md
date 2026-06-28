# Подготовка документации Delta Lake

Инструкции по подготовке документации Delta Lake из `data/source/delta/` в `data/prepared/delta/`.

## Назначение

RAG-сервер индексирует только `.md` файлы. Исходная документация Delta Lake поставляется в формате Astro/Starlight (`.mdx`) с компонентами `<Tabs>`, `<Aside>`, `<TabItem>` и т.д., которые не подходят для индексации. Кроме того, репозиторий содержит много нерелевантного контента: Scala-примеры, Java Kernel API, интеграции с Athena/BigQuery/Flink/Trino и проч.

Скрипт `prepare.py` решает обе проблемы:
1. Удаляет все нерелевантные файлы
2. Конвертирует `.mdx` → чистый `.md`
3. Конвертирует `.py` примеры → `.md` с код-блоками

## Использование

```bash
# Просмотр что будет сделано (dry-run)
uv run python -m preparers.cli --framework delta

# Применение изменений
uv run python -m preparers.cli --framework delta --execute
```

Подготовка выполняется на хосте (не в Docker) через uv. Каждый preparer читает из `data/source/{framework}/` и пишет в `data/prepared/{framework}/` через атомарный staging-rename — это гарантирует, что `make ingest` всегда читает консистентный snapshot.

## Критерии отбора

### Оставляем

**Документация (25 .mdx файлов):** Всё что относится к Delta Lake + PySpark/Python/SQL:

- `delta-batch` — batch reads/writes, SparkSession config
- `delta-streaming` — Structured Streaming, readStream/writeStream
- `delta-update` — DELETE, UPDATE, MERGE
- `quick-start` — установка PySpark + Delta Lake
- `delta-change-data-feed` — CDF
- `delta-spark-connect` — Delta Connect, Python client
- `delta-clustering` — liquid clustering
- `delta-column-mapping` — column mapping
- `delta-constraints` — NOT NULL, CHECK
- `delta-deletion-vectors` — deletion vectors
- `delta-faq` — FAQ
- `delta-type-widening` — type widening
- `delta-uniform` — UniForm (Iceberg compatibility)
- `delta-catalog-managed-tables` — catalog-managed tables
- `delta-default-columns` — default column values
- `delta-drop-feature` — drop table features
- `delta-row-tracking` — row IDs, commit versions
- `versioning` — protocol versioning
- `table-properties` — table properties reference
- `concurrency-control` — ACID, optimistic concurrency
- `delta-storage` — storage config (S3, ADLS, GCS)
- `best-practices` — partitioning, compaction, ZORDER
- `optimizations-oss` — OPTIMIZE, ZORDER, data skipping
- `delta-utility` — VACUUM, DESCRIBE HISTORY, и др.
- `porting` — миграция из Parquet/Hive → Delta

**Примеры (11 .py файлов):** Все PySpark-примеры из `examples/python/`.

### Удаляем

- **Build-инфраструктура:** Astro config, package.json, pnpm-lock, TypeScript, CSS, SVG
- **Java/Rust:** delta-kernel, delta-kernel-java, delta-kernel-rust, delta-standalone
- **Не-PySpark интеграции:** Athena, BigQuery, Flink, Hive, Presto, Trino, Starburst, Snowflake, Redshift, Delta Sharing
- **Scala примеры:** весь `examples/scala/`
- **Прочее:** PDF cheat sheet, release notes, ресурсы, API docs

## Конвертация MDX → MD

Правила преобразования:

| MDX-элемент | Markdown-эквивалент |
|---|---|
| YAML frontmatter `--- title: ... ---` | `# Title` в начале файла |
| `import { ... } from "..."` | Удалить |
| `<Tabs>` / `<TabItem label="Python">` | `#### Python` + контент (label приклеивается к следующему code block) |
| `<Aside type="note">` | `> ` (blockquote) |
| `<Aside type="caution">` | `> ` (blockquote) |
| `<Aside type="danger">` | `> ` (blockquote) |
| `<Steps>` / `<Step>` | Удалить теги |
| `<Image>` + `.png` файлы | Удалить |
| Поддиректории (`delta-streaming/index.mdx`) | Flatten: `delta-streaming.md` |

## Конвертация Python → MD

Каждый `.py` файл оборачивается:

```markdown
# Quickstart

```python
<содержимое файла>
```
```

## Финальная структура

```
data/prepared/delta/
├── docs/                          # 25 файлов
│   ├── delta-batch.md
│   ├── delta-streaming.md
│   ├── delta-update.md
│   ├── quick-start.md
│   └── ...
└── examples/                      # 11 файлов
    ├── quickstart.md
    ├── quickstart_sql.md
    └── ...
```

Итого: 36 `.md` файлов, все готовы для индексации.

## Повторная подготовка

Если нужно обновить документацию из репозитория Delta Lake:

1. Скачайте/скопируйте свежие файлы в `data/source/delta/`
2. Запустите: `uv run python -m preparers.cli --framework delta --execute`
3. Переиндексируйте: `make ingest-clear && make ingest`