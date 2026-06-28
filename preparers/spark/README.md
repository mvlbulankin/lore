# Подготовка документации Apache Spark

Инструкции по подготовке документации Apache Spark из `data/source/spark/docs/` в `data/prepared/spark/`.

## Назначение

RAG-сервер индексирует только `.md` файлы. Исходная документация Spark поставляется в формате Jekyll (`.md` с YAML frontmatter) с Liquid-тегами (`{% highlight scala %}`, `{% include %}` и т.д.), которые не подходят для индексации. Кроме того, репозиторий содержит много нерелевантного контента: Scala-примеры, Java API, ML/MLlib, GraphX, SparkR, build-инфраструктуру.

Отдельно, официальная PySpark-документация (`spark.apache.org/docs/latest/api/python/`) не входит в общий Jekyll-сайт и требует отдельного скачивания и конвертации HTML → MD.

Скрипт `prepare.py` решает обе проблемы:
1. Очищает существующие Jekyll-файлы от нерелевантного контента и конвертирует frontmatter
2. Скачивает PySpark-specific документацию и конвертирует HTML → MD
3. Фильтрует только дата-инжиниринговое направление (PySpark, Spark SQL, Structured Streaming, tuning, best practices)

## Использование

```bash
# Просмотр что будет сделано (dry-run)
uv run python -m preparers.cli --framework spark --no-download

# Только Jekyll-файлы (без скачивания)
uv run python -m preparers.cli --framework spark --no-download --execute

# Полная подготовка (Jekyll + PySpark HTML download)
uv run python -m preparers.cli --framework spark --execute
```

Подготовка выполняется на хосте (не в Docker) через uv. Атомарный staging-rename гарантирует, что `make ingest` всегда читает консистентный snapshot.

## Критерии отбора

### Оставляем (из существующих Jekyll-файлов)

**SQL и DataFrames (~95 файлов):** все `sql-*`, `sql-ref-*`, `sql-data-sources-*`.

**Structured Streaming (~12 файлов):** `structured-streaming-*`, `streaming/structured-streaming-*`, `streaming/performance-tips.md`, `streaming/real-time-mode.md`, `streaming-kafka-integration.md`, `ss-migration-guide.md`.

**Core и конфигурация (~8 файлов):** `configuration.md`, `tuning.md`, `programming-guide.md`, `quick-start.md`, `pyspark-migration-guide.md`, `migration-guide.md`, `spark-connect-*`, `app-dev-spark-connect.md`, `declarative-pipelines-programming-guide.md`.

### Удаляем

- **ML/MLlib (~36 файлов):** все `ml-*`, `mllib-*` (machine learning не нужен)
- **GraphX:** `graphx-programming-guide.md`
- **SparkR:** `sparkr.md`, `sparkr-migration-guide.md`
- **Build/Deployment:** `building-spark.md`, `hadoop-provided.md`
- **Cluster Managers:** `cluster-overview.md`, `spark-standalone.md`, `running-on-kubernetes.md`, `running-on-yarn.md`
- **Инфраструктура:** `monitoring.md`, `web-ui.md`, `job-scheduling.md`, `hardware-provisioning.md`, `security.md`, `cloud-integration.md`, `submitting-applications.md`
- **Legacy Streaming:** `streaming-programming-guide.md`, `streaming-custom-receivers.md`, `streaming-kafka-integration.md` (старый), `streaming-kinesis-integration.md`
- **Jekyll-инфраструктура:** `_data/`, `_includes/`, `_layouts/`, `_plugins/`, `css/`, `js/`, `img/`, `Gemfile*`, `_config.yml`, `README.md`, `index.md`, `404.md`, `control-flow/`

### Скачиваем и добавляем (PySpark-specific)

**Getting Started (~5 файлов):** install, quickstart_df, quickstart_connect, testing_pyspark.

**User Guide (~7 файлов):** dataframes, touroftypes, dataprep, bugbusting, udfandudtf, sql, loadandbehold.

**Tutorials (~6 файлов):** python_packaging, arrow_pandas, python_udtf, python_data_source, type_conversions.

**Reference Index (~5 файлов):** pyspark.sql/index, pyspark.sql/dataframe, pyspark.sql/functions, pyspark.ss/index, pyspark.html.

## Конвертация Jekyll frontmatter → MD

Правила преобразования:

| Jekyll-элемент | Markdown-эквивалент |
|---|---|
| YAML frontmatter `--- title: ... ---` | `# Title` в начале файла |
| `{% highlight scala %}` / `{% endhighlight %}` | Удалить (Scala-код не нужен) |
| `{% highlight java %}` / `{% endhighlight %}` | Удалить (Java-код не нужен) |
| `{% highlight python %}` / `{% endhighlight %}` | ```python (оставить) |
| `{% highlight sql %}` / `{% endhighlight %}` | ```sql (оставить) |
| `{% highlight r %}` / `{% endhighlight %}` | Удалить (R-код не нужен) |
| `{% include ... %}` | Удалить |
| `{:toc}` | Удалить |
| `* This will become a table of contents ...` | Удалить |
| License block | Удалить |

## Конвертация HTML → MD (PySpark docs)

Используется `BeautifulSoup` для парсинга HTML + ручная обработка:
- Извлечение основного контента (`<main>` / `#main-content`)
- Конвертация `<h1>`-`<h6>` → `#`-`######`
- Конвертация `<code>` → `` ` `` и `<pre>` → ` ``` `
- Удаление навигации, сайдбаров, футеров
- Удаление `<img>` тегов

## Финальная структура

```
data/prepared/spark/
├── spark-sql-programming-guide.md
├── spark-sql-getting-started.md
├── spark-sql-performance-tuning.md
├── spark-sql-data-sources-*.md
├── spark-sql-ref-*.md
├── spark-structured-streaming-*.md
├── spark-configuration.md
├── spark-tuning.md
├── spark-pyspark-migration-guide.md
├── spark-spark-connect-*.md
├── pyspark-getting-started-*.md
├── pyspark-user-guide-*.md
├── pyspark-tutorial-*.md
└── pyspark-ref-*.md
```

Итого: ~180 `.md` файлов (159 Jekyll + 21 PySpark HTML).

## Повторная подготовка

Если нужно обновить документацию:

1. Скопируйте свежие Jekyll-файлы в `data/source/spark/docs/`
2. Запустите: `uv run python -m preparers.cli --framework spark --execute`
3. Переиндексируйте: `make ingest-clear && make ingest`

## Гaps (чего не хватает)

| Тема | Статус | Причина |
|------|--------|---------|
| PySpark Best Practices | ❌ | Нет отдельного документа в официальной документации |
| Spark Performance Tuning (PySpark-specific) | ⚠️ частично | Есть общий tuning.md, но нет PySpark-специфичных рекомендаций |
| Production Deployment (K8s, YARN) | ❌ | Удалены как нерелевантные для дата-инженера в контексте RAG |
| Spark Core RDD API Reference | ❌ | RDD API deprecated, рекомендуется DataFrame API |
| Pandas API on Spark | ❌ | Отдельный модуль, не входит в основной PySpark-фреймворк |
| Declarative Pipelines Reference | ⚠️ частично | Есть programming guide, но нет API reference |