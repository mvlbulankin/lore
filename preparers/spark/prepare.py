#!/usr/bin/env python3
"""Apache Spark documentation preparer.

Reads from data/source/spark/docs (Jekyll) plus downloads PySpark HTML docs,
produces clean .md files under data/prepared/spark via atomic staging rename.

Usage:
    python -m preparers.cli --framework spark --execute
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as md

from preparers.base import PreparedDoc
from preparers._atomic import _atomic_publish


PYSPARK_BASE_URL = "https://spark.apache.org/docs/latest/api/python"

# Loaded from keep_patterns.json (external config) for easy maintenance.
_KEEP_PATTERNS_PATH = Path(__file__).parent / "keep_patterns.json"
_KEEP_PATTERNS: set[str] = set(
    json.loads(_KEEP_PATTERNS_PATH.read_text(encoding="utf-8"))
)


PYSPARK_PAGES: list[str] = [
    "getting_started/install.html",
    "getting_started/quickstart_df.html",
    "getting_started/quickstart_connect.html",
    "getting_started/testing_pyspark.html",
    "user_guide/dataframes.html",
    "user_guide/touroftypes.html",
    "user_guide/dataprep.html",
    "user_guide/bugbusting.html",
    "user_guide/udfandudtf.html",
    "user_guide/sql.html",
    "user_guide/loadandbehold.html",
    "tutorial/python_packaging.html",
    "tutorial/sql/arrow_pandas.html",
    "tutorial/sql/python_udtf.html",
    "tutorial/sql/python_data_source.html",
    "tutorial/sql/type_conversions.html",
    "reference/pyspark.sql/dataframe.html",
    "reference/pyspark.sql/functions.html",
    "reference/pyspark.html",
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
            if rel in _KEEP_PATTERNS:
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
        if _is_useless_stub(content):
            return None
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
                    for url_path in PYSPARK_PAGES:
                        url = f"{PYSPARK_BASE_URL}/{url_path}"
                        try:
                            r = client.get(url)
                            r.raise_for_status()
                        except httpx.HTTPError as e:
                            print(f"  [WARN] {url_path}: {e}", file=sys.stderr)
                            continue
                        md_text = html_to_markdown(r.text)
                        if not md_text.strip():
                            print(
                                f"  [WARN] empty content for {url_path}",
                                file=sys.stderr,
                            )
                            continue
                        if _is_useless_stub(md_text):
                            print(f"  [SKIP] stub: {url_path}", file=sys.stderr)
                            continue
                        out_name = _title_to_filename(_extract_h1(r.text))
                        print(f"  downloaded → {out_name}")
                        docs.append(
                            PreparedDoc(relative_path=out_name, content=md_text)
                        )
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
            for url_path in PYSPARK_PAGES:
                print(f"  [DL  ] {url_path}")
        print(f"[spark] ~{kept + len(PYSPARK_PAGES)} total files")


def _strip_frontmatter(content: str) -> str:
    content = re.sub(
        r"^---\s*\n.*?^---\s*\n", "", content, flags=re.DOTALL | re.MULTILINE
    )
    content = re.sub(
        r"^license:\s*\|.*?(?=\n---|\n[A-Z]|\n#\s|\n\*|\n\n\w)",
        "",
        content,
        flags=re.DOTALL | re.MULTILINE,
    )
    return content


def _extract_title(content: str) -> str:
    fm_match = re.search(
        r"^---\s*\n.*?title:\s*(.+?)\s*\n", content, flags=re.DOTALL | re.MULTILINE
    )
    if fm_match:
        return fm_match.group(1).strip()
    h1_match = re.search(r"^#\s+(.+)$", content, flags=re.MULTILINE)
    if h1_match:
        return h1_match.group(1).strip()
    return ""


def _strip_scala_java_code(content: str) -> str:
    content = re.sub(
        r"\{%\s*highlight\s+scala\s*%\}.*?\{%\s*endhighlight\s*%\}",
        "",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    content = re.sub(
        r"\{%\s*highlight\s+java\s*%\}.*?\{%\s*endhighlight\s*%\}",
        "",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    content = re.sub(
        r"\{%\s*highlight\s+r\s*%\}.*?\{%\s*endhighlight\s*%\}",
        "",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    content = re.sub(
        r"\{%\s*highlight\s+sql\s*%\}", "```sql", content, flags=re.IGNORECASE
    )
    content = re.sub(
        r"\{%\s*highlight\s+python\s*%\}", "```python", content, flags=re.IGNORECASE
    )
    content = re.sub(
        r"\{%\s*highlight\s+(?:shell|bash)\s*%\}",
        "```bash",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(r"\{%\s*/?\s*highlight\s*%\}", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\{%\s*endhighlight\s*%\}", "```", content, flags=re.IGNORECASE)
    return content


def _strip_liquid_tags(content: str) -> str:
    content = re.sub(r"\{\{[^}]*\}\}", "", content)
    content = re.sub(r"\{%[^%]*%\}", "", content)
    return content


def _strip_html_divs(content: str) -> str:
    content = re.sub(
        r'<div\s+data-lang="scala"[^>]*>.*?</div>',
        "",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    content = re.sub(
        r'<div\s+data-lang="java"[^>]*>.*?</div>',
        "",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    content = re.sub(
        r'<div\s+data-lang="r"[^>]*>.*?</div>',
        "",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    content = re.sub(r'<div\s+class="codetabs"[^>]*>', "", content, flags=re.IGNORECASE)
    content = re.sub(
        r'<div\s+data-lang="python"[^>]*>', "", content, flags=re.IGNORECASE
    )
    content = re.sub(r'<div\s+markdown="1"[^>]*>', "", content, flags=re.IGNORECASE)
    content = re.sub(r"</div>\s*\n", "\n", content, flags=re.IGNORECASE)
    content = re.sub(r"\n</div>", "\n", content, flags=re.IGNORECASE)
    return content


def _clean_toc_markers(content: str) -> str:
    content = re.sub(r"\{:toc\}", "", content)
    content = re.sub(
        r"\*\s*This will become a table of contents.*?\*", "", content, flags=re.DOTALL
    )
    return content


def _strip_include_tags(content: str) -> str:
    content = re.sub(r"\{%\s*include\s+[^%]*%\}", "", content, flags=re.DOTALL)
    return content


def _is_useless_stub(content: str) -> bool:
    """Check if the cleaned content has no meaningful documentation value."""
    lines = [line.strip() for line in content.strip().split("\n") if line.strip()]
    # Only check non-code lines for redirect/placeholder keywords
    prose_lines = [line for line in lines if not line.startswith("```")]
    prose_text = " ".join(prose_lines).lower()

    # Redirect / archived pages
    if any(kw in prose_text for kw in ("has moved", "moved [here]", "archived on")):
        return True
    if re.search(r"\bredirect\b", prose_text):
        return True
    if "[here](" in prose_text:
        return True

    # Under construction / placeholder
    if "under construction" in prose_text:
        return True

    # Heading-only: mostly headings with no prose
    if len(lines) >= 5:
        heading_lines = sum(1 for line in lines if line.startswith("#"))
        if heading_lines > len(lines) * 0.7 and heading_lines >= 10:
            return True

    # Tiny stubs: title + single sentence with no real content
    if len(lines) <= 2:
        non_heading = [line for line in lines if not line.startswith("#")]
        if len(non_heading) <= 1:
            body = " ".join(non_heading).lower()
            if "overview" in body or "gives an overview" in body:
                return True

    return False


def clean_jekyll_md(content: str) -> str:
    title = _extract_title(content)
    content = _strip_frontmatter(content)
    content = _strip_include_tags(content)
    content = _strip_scala_java_code(content)
    content = _strip_liquid_tags(content)
    content = _strip_html_divs(content)
    content = _clean_toc_markers(content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    text = content.strip()
    if title and not text.startswith("# "):
        text = f"# {title}\n\n{text}"
    return text + "\n"


def _clean_notebook_html(soup: BeautifulSoup) -> None:
    """Strip nbsphinx notebook artifacts: nboutput cells, prompts, and cell markers.

    Keeps only the code from input_area elements inside nbinput containers.
    """
    for nboutput in soup.find_all("div", class_=re.compile(r"nboutput", re.I)):
        nboutput.decompose()
    for prompt in soup.find_all("div", class_=re.compile(r"prompt", re.I)):
        prompt.decompose()
    for nbinput in soup.find_all("div", class_=re.compile(r"nbinput", re.I)):
        input_area = nbinput.find("div", class_=re.compile(r"input_area", re.I))
        if input_area and input_area != nbinput:
            highlight = input_area.find("div", class_=re.compile(r"highlight", re.I))
            if highlight:
                pre = highlight.find("pre")
                if pre:
                    code = pre.get_text()
                    lang_class = ""
                    for cls in input_area.get("class") or []:
                        if cls.startswith("highlight-"):
                            lang_class = cls
                            break
                    nbinput.clear()
                    nbinput.append(input_area)
                    input_area.clear()
                    input_area["class"] = ["input_area"]
                    if lang_class:
                        input_area["class"].append(lang_class)
                    new_pre = soup.new_tag("pre")
                    new_pre.string = code
                    input_area.append(new_pre)


def _clean_notebook_md(text: str) -> str:
    """Post-process markdown from notebook HTML to remove remaining artifacts."""
    lines = text.split("\n")
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            fence_content: list[str] = [line]
            lang = stripped[3:].strip()
            i += 1
            closed = False
            while i < len(lines):
                if lines[i].strip().startswith("```"):
                    fence_content.append(lines[i])
                    closed = True
                    i += 1
                    break
                fence_content.append(lines[i])
                i += 1
            if not closed:
                fence_content.append("```")

            inner_lines = fence_content[1:-1]
            while inner_lines and re.match(r"^\[\d+\]:\s*$", inner_lines[0].strip()):
                inner_lines = inner_lines[1:]
            if (
                not inner_lines
                or not " ".join(line.strip() for line in inner_lines).strip()
            ):
                continue
            if not lang:
                lang = "python"
            result.append(f"```{lang}")
            result.extend(inner_lines)
            result.append("```")
        else:
            result.append(line)
            i += 1

    return "\n".join(result)


def _title_to_filename(title: str) -> str:
    """Convert H1 title to a clean filename slug."""
    slug = title.lower().rstrip("#")
    # Strip "Chapter N:" prefix
    slug = re.sub(r"^chapter\s*\d+[:\s-]*", "", slug)
    # Strip subtitle after " - " (hyphen with spaces on both sides)
    slug = re.sub(r" - .+", "", slug, count=1)
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return f"pyspark-{slug}.md"


def _extract_h1(html_content: str) -> str:
    """Extract H1 title from HTML page."""
    soup = BeautifulSoup(html_content, "html.parser")
    main = soup.find("main") or soup.find(id="main-content") or soup.find("article")
    if not main:
        main = soup.find("body")
    if not main:
        return ""
    title_tag = main.find("h1")
    return title_tag.get_text(strip=True) if title_tag else ""


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
    for tag in main.find_all(
        class_=re.compile(r"(sidebar|toctree|related|rellinks|checkboxes)", re.I)
    ):
        tag.decompose()
    for a in main.find_all("a", href=re.compile(r"_sources/", re.I)):
        a.decompose()
    for a in main.find_all("a", class_=re.compile(r"headerlink|reference", re.I)):
        a.decompose()
    for div in main.find_all(
        "div", class_=re.compile(r"(prev-next|related|toctree)", re.I)
    ):
        div.decompose()
    _clean_notebook_html(soup)
    md_text = md(str(main), heading_style="ATX")
    md_text = _clean_notebook_md(md_text)
    md_text = re.sub(r"\n{3,}", "\n\n", md_text)
    md_text = md_text.strip()
    if title and not md_text.startswith("# "):
        md_text = f"# {title}\n\n{md_text}"
    return md_text + "\n"


PREPARER = SparkPreparer()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Apache Spark docs preparer (standalone)"
    )
    parser.add_argument("--source-root", type=Path, default=Path("data/source"))
    parser.add_argument("--prepared-root", type=Path, default=Path("data/prepared"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--no-download", action="store_true", help="Skip PySpark HTML download"
    )
    args = parser.parse_args()
    PREPARER.source_dir = args.source_root / "spark"
    PREPARER.prepared_dir = args.prepared_root / "spark"
    if args.no_download:
        PREPARER.download_pyspark = False
    PREPARER.run(execute=args.execute)
