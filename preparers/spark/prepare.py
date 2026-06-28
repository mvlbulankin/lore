#!/usr/bin/env python3
"""Apache Spark documentation preparer.

Reads from data/source/spark/docs (Jekyll) plus downloads PySpark HTML docs,
produces clean .md files under data/prepared/spark via atomic staging rename.

Usage:
    python -m preparers.cli --framework spark --execute
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as md

from preparers.base import PreparedDoc
from preparers._atomic import _atomic_publish


PYSPIRK_BASE_URL = "https://spark.apache.org/docs/latest/api/python"

KEEP_PATTERNS: list[str] = [
    # SQL programming and data sources
    "sql-programming-guide.md",
    "sql-getting-started.md",
    "sql-performance-tuning.md",
    "sql-pyspark-pandas-with-arrow.md",
    "sql-distributed-sql-engine.md",
    "sql-distributed-sql-engine-spark-sql-cli.md",
    "sql-migration-guide.md",
    "sql-error-conditions.md",
    "sql-ref.md",
    "sql-ref-datatypes.md",
    "sql-ref-operators.md",
    "sql-ref-functions.md",
    "sql-ref-functions-builtin.md",
    "sql-ref-functions-udf-scalar.md",
    "sql-ref-functions-udf-aggregate.md",
    "sql-ref-functions-udf-hive.md",
    "sql-ref-ansi-compliance.md",
    "sql-ref-null-semantics.md",
    "sql-ref-name-resolution.md",
    "sql-ref-identifier.md",
    "sql-ref-identifier-clause.md",
    "sql-ref-literals.md",
    "sql-ref-datetime-pattern.md",
    "sql-ref-number-pattern.md",
    "sql-ref-parameter-markers.md",
    "sql-ref-scripting.md",
    "sql-ref-sketch-aggregates.md",
    "sql-ref-geospatial-types.md",
    "sql-ref-function-invocation.md",
    "sql-ref-function-current-path.md",
    # SQL data sources
    "sql-data-sources.md",
    "sql-data-sources-parquet.md",
    "sql-data-sources-json.md",
    "sql-data-sources-csv.md",
    "sql-data-sources-avro.md",
    "sql-data-sources-orc.md",
    "sql-data-sources-jdbc.md",
    "sql-data-sources-text.md",
    "sql-data-sources-binaryFile.md",
    "sql-data-sources-xml.md",
    "sql-data-sources-protobuf.md",
    "sql-data-sources-generic-options.md",
    "sql-data-sources-load-save-functions.md",
    "sql-data-sources-v2.md",
    "sql-data-sources-troubleshooting.md",
    "sql-data-sources-hive-tables.md",
    # SQL syntax reference
    "sql-ref-syntax.md",
    "sql-ref-syntax-qry-select.md",
    "sql-ref-syntax-qry-select-aggregate.md",
    "sql-ref-syntax-qry-select-case.md",
    "sql-ref-syntax-qry-select-clusterby.md",
    "sql-ref-syntax-qry-select-cte.md",
    "sql-ref-syntax-qry-select-distribute-by.md",
    "sql-ref-syntax-qry-select-file.md",
    "sql-ref-syntax-qry-select-groupby.md",
    "sql-ref-syntax-qry-select-having.md",
    "sql-ref-syntax-qry-select-hints.md",
    "sql-ref-syntax-qry-select-inline-table.md",
    "sql-ref-syntax-qry-select-join.md",
    "sql-ref-syntax-qry-select-lateral-subquery.md",
    "sql-ref-syntax-qry-select-lateral-view.md",
    "sql-ref-syntax-qry-select-like.md",
    "sql-ref-syntax-qry-select-limit.md",
    "sql-ref-syntax-qry-select-offset.md",
    "sql-ref-syntax-qry-select-orderby.md",
    "sql-ref-syntax-qry-select-pivot.md",
    "sql-ref-syntax-qry-select-qualify.md",
    "sql-ref-syntax-qry-select-sampling.md",
    "sql-ref-syntax-qry-select-setops.md",
    "sql-ref-syntax-qry-select-sortby.md",
    "sql-ref-syntax-qry-select-subqueries.md",
    "sql-ref-syntax-qry-select-transform.md",
    "sql-ref-syntax-qry-select-tvf.md",
    "sql-ref-syntax-qry-select-unpivot.md",
    "sql-ref-syntax-qry-select-where.md",
    "sql-ref-syntax-qry-select-window.md",
    "sql-ref-syntax-qry-star.md",
    "sql-ref-syntax-qry-explain.md",
    "sql-ref-syntax-ddl-create-table.md",
    "sql-ref-syntax-ddl-create-table-datasource.md",
    "sql-ref-syntax-ddl-create-table-hiveformat.md",
    "sql-ref-syntax-ddl-create-table-like.md",
    "sql-ref-syntax-ddl-create-view.md",
    "sql-ref-syntax-ddl-create-database.md",
    "sql-ref-syntax-ddl-create-function.md",
    "sql-ref-syntax-ddl-create-sql-function.md",
    "sql-ref-syntax-ddl-alter-table.md",
    "sql-ref-syntax-ddl-alter-database.md",
    "sql-ref-syntax-ddl-alter-view.md",
    "sql-ref-syntax-ddl-drop-table.md",
    "sql-ref-syntax-ddl-drop-database.md",
    "sql-ref-syntax-ddl-drop-function.md",
    "sql-ref-syntax-ddl-drop-view.md",
    "sql-ref-syntax-ddl-drop-variable.md",
    "sql-ref-syntax-ddl-declare-variable.md",
    "sql-ref-syntax-ddl-usedb.md",
    "sql-ref-syntax-ddl-repair-table.md",
    "sql-ref-syntax-ddl-truncate-table.md",
    "sql-ref-syntax-dml-insert-table.md",
    "sql-ref-syntax-dml-insert-overwrite-directory.md",
    "sql-ref-syntax-dml-load.md",
    "sql-ref-syntax-dml-merge-into.md",
    "sql-ref-syntax-aux-cache.md",
    "sql-ref-syntax-aux-cache-cache-table.md",
    "sql-ref-syntax-aux-cache-clear-cache.md",
    "sql-ref-syntax-aux-cache-refresh.md",
    "sql-ref-syntax-aux-cache-refresh-table.md",
    "sql-ref-syntax-aux-cache-refresh-function.md",
    "sql-ref-syntax-aux-cache-uncache-table.md",
    "sql-ref-syntax-aux-conf-mgmt.md",
    "sql-ref-syntax-aux-conf-mgmt-set.md",
    "sql-ref-syntax-aux-conf-mgmt-set-path.md",
    "sql-ref-syntax-aux-conf-mgmt-set-timezone.md",
    "sql-ref-syntax-aux-conf-mgmt-reset.md",
    "sql-ref-syntax-aux-describe.md",
    "sql-ref-syntax-aux-describe-table.md",
    "sql-ref-syntax-aux-describe-database.md",
    "sql-ref-syntax-aux-describe-function.md",
    "sql-ref-syntax-aux-describe-query.md",
    "sql-ref-syntax-aux-show.md",
    "sql-ref-syntax-aux-show-tables.md",
    "sql-ref-syntax-aux-show-table.md",
    "sql-ref-syntax-aux-show-databases.md",
    "sql-ref-syntax-aux-show-columns.md",
    "sql-ref-syntax-aux-show-functions.md",
    "sql-ref-syntax-aux-show-views.md",
    "sql-ref-syntax-aux-show-partitions.md",
    "sql-ref-syntax-aux-show-create-table.md",
    "sql-ref-syntax-aux-show-tblproperties.md",
    "sql-ref-syntax-aux-show-collations.md",
    "sql-ref-syntax-aux-resource-mgmt.md",
    "sql-ref-syntax-aux-resource-mgmt-add-file.md",
    "sql-ref-syntax-aux-resource-mgmt-add-jar.md",
    "sql-ref-syntax-aux-resource-mgmt-add-archive.md",
    "sql-ref-syntax-aux-resource-mgmt-list-file.md",
    "sql-ref-syntax-aux-resource-mgmt-list-jar.md",
    "sql-ref-syntax-aux-resource-mgmt-list-archive.md",
    "sql-ref-syntax-aux-analyze-table.md",
    "sql-ref-syntax-aux-set-var.md",
    "sql-ref-syntax-aux-exec-imm.md",
    "sql-ref-syntax-hive-format.md",
    # Core docs
    "configuration.md",
    "tuning.md",
    "programming-guide.md",
    "quick-start.md",
    "pyspark-migration-guide.md",
    "migration-guide.md",
    "spark-connect-overview.md",
    "spark-connect-gotchas.md",
    "app-dev-spark-connect.md",
    "declarative-pipelines-programming-guide.md",
    # Structured Streaming
    "structured-streaming-programming-guide.md",
    "ss-migration-guide.md",
    "streaming/structured-streaming-kafka-integration.md",
    "streaming/structured-streaming-state-data-source.md",
    "streaming/structured-streaming-transform-with-state.md",
    "streaming/performance-tips.md",
    "streaming/real-time-mode.md",
    "streaming/additional-information.md",
]


PYSPIRK_PAGES: list[tuple[str, str]] = [
    ("getting_started/install.html", "pyspark-getting-started-install.md"),
    ("getting_started/quickstart_df.html", "pyspark-getting-started-quickstart-df.md"),
    ("getting_started/quickstart_connect.html", "pyspark-getting-started-quickstart-connect.md"),
    ("getting_started/testing_pyspark.html", "pyspark-getting-started-testing.md"),
    ("user_guide/dataframes.html", "pyspark-user-guide-dataframes.md"),
    ("user_guide/touroftypes.html", "pyspark-user-guide-touroftypes.md"),
    ("user_guide/dataprep.html", "pyspark-user-guide-dataprep.md"),
    ("user_guide/bugbusting.html", "pyspark-user-guide-bugbusting.md"),
    ("user_guide/udfandudtf.html", "pyspark-user-guide-udfandudtf.md"),
    ("user_guide/sql.html", "pyspark-user-guide-sql.md"),
    ("user_guide/loadandbehold.html", "pyspark-user-guide-loadandbehold.md"),
    ("tutorial/python_packaging.html", "pyspark-tutorial-python-packaging.md"),
    ("tutorial/sql/arrow_pandas.html", "pyspark-tutorial-sql-arrow-pandas.md"),
    ("tutorial/sql/python_udtf.html", "pyspark-tutorial-sql-python-udtf.md"),
    ("tutorial/sql/python_data_source.html", "pyspark-tutorial-sql-python-data-source.md"),
    ("tutorial/sql/type_conversions.html", "pyspark-tutorial-sql-type-conversions.md"),
    ("reference/pyspark.sql/index.html", "pyspark-ref-sql-index.md"),
    ("reference/pyspark.sql/dataframe.html", "pyspark-ref-sql-dataframe.md"),
    ("reference/pyspark.sql/functions.html", "pyspark-ref-sql-functions.md"),
    ("reference/pyspark.ss/index.html", "pyspark-ref-streaming-index.md"),
    ("reference/pyspark.html", "pyspark-ref-core.md"),
]


@dataclass
class SparkPreparer:
    name: str = "spark"
    source_dir: Path = field(default_factory=Path)
    prepared_dir: Path = field(default_factory=Path)
    download_pyspark: bool = True

    def discover(self) -> list[Path]:
        out: list[Path] = []
        docs_dir = self.source_dir / "docs"
        if not docs_dir.exists():
            return out
        for src in sorted(docs_dir.rglob("*.md")):
            rel = src.relative_to(docs_dir).as_posix()
            if rel in KEEP_PATTERNS:
                out.append(src)
        return out

    def transform(self, src: Path) -> PreparedDoc | None:
        docs_dir = self.source_dir / "docs"
        rel = src.relative_to(docs_dir)
        stem = src.stem
        if str(rel.parent) != ".":
            out_name = f"spark-{rel.parent.name}-{stem}.md"
        else:
            out_name = f"spark-{stem}.md"
        content = clean_jekyll_md(src.read_text(encoding="utf-8"))
        return PreparedDoc(relative_path=out_name, content=content)

    def cleanup(self) -> None:
        return

    def run(self, execute: bool = False) -> None:
        if not execute:
            self._dry_run()
            return

        print(f"[spark] staging → {self.prepared_dir}")
        staging = self.prepared_dir.parent / f"_prepared_{self.name}_staging"

        def _build() -> list[PreparedDoc]:
            docs: list[PreparedDoc] = []
            for src in self.discover():
                doc = self.transform(src)
                if doc is None:
                    continue
                print(f"  {src.name} → {doc.relative_path}")
                docs.append(doc)
            if self.download_pyspark:
                with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                    for url_path, out_name in PYSPIRK_PAGES:
                        url = f"{PYSPIRK_BASE_URL}/{url_path}"
                        try:
                            r = client.get(url)
                            r.raise_for_status()
                        except httpx.HTTPError as e:
                            print(f"  [WARN] {url_path}: {e}", file=sys.stderr)
                            continue
                        md_text = html_to_markdown(r.text)
                        if not md_text.strip():
                            print(f"  [WARN] empty content for {url_path}", file=sys.stderr)
                            continue
                        print(f"  downloaded → {out_name}")
                        docs.append(PreparedDoc(relative_path=out_name, content=md_text))
            return docs

        n = _atomic_publish(self.prepared_dir, staging, _build)
        print(f"[spark] prepared {n} files")

    def _dry_run(self) -> None:
        print(f"[spark] dry-run (source={self.source_dir})")
        kept = 0
        for src in self.discover():
            print(f"  [KEEP] {src.name}")
            kept += 1
        if self.download_pyspark:
            for url_path, out_name in PYSPIRK_PAGES:
                print(f"  [DL  ] {url_path} → {out_name}")
        print(f"[spark] ~{kept + len(PYSPIRK_PAGES)} total files")


def _strip_frontmatter(content: str) -> str:
    content = re.sub(r'^---\s*\n.*?^---\s*\n', '', content, flags=re.DOTALL | re.MULTILINE)
    content = re.sub(
        r'^license:\s*\|.*?(?=\n---|\n[A-Z]|\n#\s|\n\*|\n\n\w)',
        '',
        content,
        flags=re.DOTALL | re.MULTILINE,
    )
    return content


def _extract_title(content: str) -> str:
    fm_match = re.search(r'^---\s*\n.*?title:\s*(.+?)\s*\n', content, flags=re.DOTALL | re.MULTILINE)
    if fm_match:
        return fm_match.group(1).strip()
    h1_match = re.search(r'^#\s+(.+)$', content, flags=re.MULTILINE)
    if h1_match:
        return h1_match.group(1).strip()
    return ""


def _strip_scala_java_code(content: str) -> str:
    content = re.sub(r'\{%\s*highlight\s+scala\s*%\}.*?\{%\s*endhighlight\s*%\}', '', content, flags=re.DOTALL)
    content = re.sub(r'\{%\s*highlight\s+java\s*%\}.*?\{%\s*endhighlight\s*%\}', '', content, flags=re.DOTALL)
    content = re.sub(r'\{%\s*highlight\s+r\s*%\}.*?\{%\s*endhighlight\s*%\}', '', content, flags=re.DOTALL)
    content = re.sub(r'\{%\s*highlight\s+sql\s*%\}', '```sql', content, flags=re.IGNORECASE)
    content = re.sub(r'\{%\s*endhighlight\s*%\}', '```', content, flags=re.IGNORECASE)
    content = re.sub(r'\{%\s*highlight\s+python\s*%\}', '```python', content, flags=re.IGNORECASE)
    content = re.sub(r'\{%\s*highlight\s+scala\s*%\}', '', content, flags=re.IGNORECASE)
    content = re.sub(r'\{%\s*highlight\s+java\s*%\}', '', content, flags=re.IGNORECASE)
    content = re.sub(r'\{%\s*highlight\s+r\s*%\}', '', content, flags=re.IGNORECASE)
    content = re.sub(r'\{%\s*highlight\s+(?:shell|bash)\s*%\}', '```bash', content, flags=re.IGNORECASE)
    content = re.sub(r'\{%\s*endhighlight\s*%\}', '```', content, flags=re.IGNORECASE)
    return content


def _strip_liquid_tags(content: str) -> str:
    content = re.sub(r'\{\{[^}]*\}\}', '', content)
    content = re.sub(r'\{%[^%]*%\}', '', content)
    return content


def _strip_html_divs(content: str) -> str:
    content = re.sub(
        r'<div\s+data-lang="scala"[^>]*>.*?</div>',
        '',
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    content = re.sub(
        r'<div\s+data-lang="java"[^>]*>.*?</div>',
        '',
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    content = re.sub(
        r'<div\s+data-lang="r"[^>]*>.*?</div>',
        '',
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    content = re.sub(r'<div\s+class="codetabs"[^>]*>', '', content, flags=re.IGNORECASE)
    content = re.sub(r'<div\s+data-lang="python"[^>]*>', '', content, flags=re.IGNORECASE)
    content = re.sub(r'<div\s+markdown="1"[^>]*>', '', content, flags=re.IGNORECASE)
    content = re.sub(r'</div>\s*\n', '\n', content, flags=re.IGNORECASE)
    content = re.sub(r'\n</div>', '\n', content, flags=re.IGNORECASE)
    return content


def _clean_toc_markers(content: str) -> str:
    content = re.sub(r'\{:toc\}', '', content)
    content = re.sub(r'\*\s*This will become a table of contents.*?\*', '', content, flags=re.DOTALL)
    return content


def _strip_include_tags(content: str) -> str:
    content = re.sub(r'\{%\s*include\s+[^%]*%\}', '', content, flags=re.DOTALL)
    return content


def clean_jekyll_md(content: str) -> str:
    title = _extract_title(content)
    content = _strip_frontmatter(content)
    content = _strip_include_tags(content)
    content = _strip_scala_java_code(content)
    content = _strip_liquid_tags(content)
    content = _strip_html_divs(content)
    content = _clean_toc_markers(content)
    content = re.sub(r'\n{3,}', '\n\n', content)
    text = content.strip()
    if title and not text.startswith("# "):
        text = f"# {title}\n\n{text}"
    return text + "\n"


def html_to_markdown(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")
    main = soup.find("main") or soup.find(id="main-content") or soup.find("article")
    if not main:
        main = soup.find("body")
    if not main:
        return ""
    title_tag = main.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else ""
    for tag_name in ("nav", "footer", "script", "style", "noscript"):
        for tag in main.find_all(tag_name):
            tag.decompose()
    for img in main.find_all("img"):
        img.decompose()
    for tag in main.find_all(class_=re.compile(r"(sidebar|toctree|related|rellinks|checkboxes)", re.I)):
        tag.decompose()
    for a in main.find_all("a", href=re.compile(r"_sources/", re.I)):
        a.decompose()
    for a in main.find_all("a", class_=re.compile(r"headerlink|reference", re.I)):
        a.decompose()
    for div in main.find_all("div", class_=re.compile(r"(prev-next|related|toctree)", re.I)):
        div.decompose()
    md_text = md(str(main), heading_style="ATX")
    md_text = re.sub(r'\n{3,}', '\n\n', md_text)
    md_text = md_text.strip()
    if title and not md_text.startswith("# "):
        md_text = f"# {title}\n\n{md_text}"
    return md_text + "\n"


PREPARER = SparkPreparer()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apache Spark docs preparer (standalone)")
    parser.add_argument("--source-root", type=Path, default=Path("data/source"))
    parser.add_argument("--prepared-root", type=Path, default=Path("data/prepared"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--no-download", action="store_true", help="Skip PySpark HTML download")
    args = parser.parse_args()
    PREPARER.source_dir = args.source_root / "spark"
    PREPARER.prepared_dir = args.prepared_root / "spark"
    if args.no_download:
        PREPARER.download_pyspark = False
    PREPARER.run(execute=args.execute)