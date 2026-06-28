#!/usr/bin/env python3
"""Delta Lake documentation preparer.

Reads from data/source/delta/{docs,examples} and produces clean .md files
under data/prepared/delta/{docs,examples} via atomic staging rename.

Usage:
    python -m preparers.cli --framework delta --execute
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from preparers.base import PreparedDoc
from preparers._atomic import _atomic_publish


KEEP_MDX = [
    "delta-batch", "delta-streaming/index", "delta-update", "quick-start",
    "delta-change-data-feed", "delta-spark-connect", "delta-clustering",
    "delta-column-mapping", "delta-constraints", "delta-deletion-vectors",
    "delta-faq", "delta-type-widening", "delta-uniform",
    "delta-catalog-managed-tables", "delta-default-columns",
    "delta-drop-feature", "delta-row-tracking", "versioning",
    "table-properties", "concurrency-control", "delta-storage",
    "best-practices", "optimizations-oss/index", "delta-utility/index",
    "porting",
]

KEEP_PY = [
    "quickstart", "quickstart_sql", "quickstart_sql_on_paths",
    "streaming", "utilities", "change_data_feed", "using_with_pip",
    "delta_connect", "image_storage", "missing_delta_storage_jar",
    "table_exists",
]


@dataclass
class DeltaPreparer:
    name: str = "delta"
    source_dir: Path = field(default_factory=Path)
    prepared_dir: Path = field(default_factory=Path)

    def discover(self) -> list[Path]:
        out: list[Path] = []
        docs_src = self.source_dir / "docs" / "src" / "content" / "docs"
        py_src = self.source_dir / "examples" / "python"
        for name in KEEP_MDX:
            p = docs_src / f"{name}.mdx"
            if p.exists():
                out.append(p)
        for name in KEEP_PY:
            p = py_src / f"{name}.py"
            if p.exists():
                out.append(p)
        return out

    def transform(self, src: Path) -> PreparedDoc | None:
        if src.suffix == ".mdx":
            rel = _mdx_target(src)
            return PreparedDoc(relative_path=f"docs/{rel}", content=_convert_mdx(src))
        if src.suffix == ".py":
            return PreparedDoc(
                relative_path=f"examples/{src.stem}.md",
                content=_convert_py(src),
            )
        return None

    def cleanup(self) -> None:
        return

    def run(self, execute: bool = False) -> None:
        if not execute:
            self._dry_run()
            return

        print(f"[delta] staging → {self.prepared_dir}")
        staging = self.prepared_dir.parent / f"_prepared_{self.name}_staging"

        def _build() -> list[PreparedDoc]:
            docs: list[PreparedDoc] = []
            for src in self.discover():
                doc = self.transform(src)
                if doc is None:
                    print(f"  [WARN] Skipped {src.name}")
                    continue
                print(f"  {src.name} → {doc.relative_path}")
                docs.append(doc)
            return docs

        n = _atomic_publish(self.prepared_dir, staging, _build)
        print(f"[delta] prepared {n} files")

    def _dry_run(self) -> None:
        print(f"[delta] dry-run (source={self.source_dir}, prepared={self.prepared_dir})")
        for src in self.discover():
            doc = self.transform(src)
            if doc is None:
                print(f"  [SKIP] {src.name}")
            else:
                print(f"  [OK ] {src.name} → {doc.relative_path}")


def _mdx_target(src: Path) -> str:
    if src.name == "index.mdx":
        return f"{src.parent.name}.md"
    return src.name.removesuffix(".mdx") + ".md"


class MDXConverter:
    """Convert .mdx (Astro/Starlight) to clean Markdown."""

    def convert(self, text: str) -> str:
        title = self._extract_title(text)
        text = self._remove_frontmatter(text)
        text = self._remove_imports(text)
        text = self._convert_tabitems(text)
        text = self._remove_tabs(text)
        text = self._convert_aside(text)
        text = self._remove_image_imports(text)
        text = self._remove_remaining_tags(text)
        text = self._clean_whitespace(text)
        return f"{title}\n{text}"

    @staticmethod
    def _extract_title(text: str) -> str:
        m = re.search(r"^---\s*\ntitle:\s*(.+)", text, re.MULTILINE)
        if m:
            return f"# {m.group(1).strip()}"
        return "# Document"

    @staticmethod
    def _remove_frontmatter(text: str) -> str:
        return re.sub(
            r"^---\s*\n.*?^---\s*\n", "", text, count=1,
            flags=re.DOTALL | re.MULTILINE,
        )

    @staticmethod
    def _remove_imports(text: str) -> str:
        return re.sub(r"^\s*import\s+.*?;\s*\n", "", text, flags=re.MULTILINE)

    def _convert_tabitems(self, text: str) -> str:
        def replacer(m: re.Match) -> str:
            label = m.group(1)
            content = m.group(2).strip()
            return f"\n#### {label}\n\n{content}\n"
        pattern = r"<TabItem\s+label=\"([^\"]+)\"[^>]*>\s*\n([\s\S]*?)\n\s*</TabItem>"
        return re.sub(pattern, replacer, text)

    @staticmethod
    def _remove_tabs(text: str) -> str:
        text = re.sub(r"<Tabs[^>]*>\s*\n", "", text)
        text = re.sub(r"\s*</Tabs>\s*\n", "\n", text)
        return text

    def _convert_aside(self, text: str) -> str:
        def replacer(m: re.Match) -> str:
            content = m.group(1).strip()
            lines = content.split("\n")
            quoted = [f"> {line}" if line.strip() else ">" for line in lines]
            return "\n" + "\n".join(quoted) + "\n"
        pattern = r"<Aside[^>]*>\s*\n([\s\S]*?)\n</Aside>"
        return re.sub(pattern, replacer, text, flags=re.DOTALL)

    @staticmethod
    def _remove_image_imports(text: str) -> str:
        return re.sub(r"^\s*import.*Image.*\s*\n", "", text, flags=re.MULTILINE)

    @staticmethod
    def _remove_remaining_tags(text: str) -> str:
        text = re.sub(r"<Steps[^>]*>", "", text)
        text = re.sub(r"</Steps>", "", text)
        text = re.sub(r"<Step[^>]*>", "", text)
        text = re.sub(r"</Step>", "", text)
        text = re.sub(r"</?[a-zA-Z][^>]*>", "", text)
        return text

    @staticmethod
    def _clean_whitespace(text: str) -> str:
        while "\n\n\n" in text:
            text = text.replace("\n\n\n", "\n\n")
        return text.strip() + "\n"


def _convert_mdx(src: Path) -> str:
    text = src.read_text(encoding="utf-8")
    return MDXConverter().convert(text)


def _convert_py(src: Path) -> str:
    code = src.read_text(encoding="utf-8")
    title = src.stem.replace("_", " ").title()
    return f"# {title}\n\n```python\n{code}\n```\n"


PREPARER = DeltaPreparer()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Delta Lake docs preparer (standalone)")
    parser.add_argument("--source-root", type=Path, default=Path("data/source"))
    parser.add_argument("--prepared-root", type=Path, default=Path("data/prepared"))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    PREPARER.source_dir = args.source_root / "delta"
    PREPARER.prepared_dir = args.prepared_root / "delta"
    PREPARER.run(execute=args.execute)