# `data/source/` — сырьё для документации

Эта директория содержит **исходные** материалы для фреймворков в их оригинальном формате:

- `spark/docs/` — Jekyll-исходники Apache Spark (`.md` + frontmatter + Liquid)
- `delta/docs/` — Astro/Starlight исходники Delta Lake (`.mdx` + компоненты)
- `delta/examples/python/` — PySpark-примеры Delta Lake (`.py`)
- `test/` — тестовый документ для smoke-test

## Что **не** нужно делать вручную

- ❌ Не редактируйте файлы здесь напрямую. Это копии из upstream-репозиториев.
- ❌ Не добавляйте новые фреймворки здесь без создания соответствующего `preparers/<framework>/prepare.py`.
- ❌ Не монтируется в Docker — используется только на хосте через `make prepare`.

## Обновление сырья

Когда upstream выпускает новую версию документации:

```bash
# Spark
cd data/source/spark && git pull
cd -

# Delta
rm -rf data/source/delta
git clone https://github.com/delta-io/delta.git data/source/delta

# Test (нет upstream)
# Файл test.md редактируется вручную
```

После обновления:

```bash
make prepare
make ingest-clear && make ingest
```