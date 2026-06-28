#!/usr/bin/env python3
"""Test framework preparer (trivial passthrough)."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

from preparers.base import PreparedDoc
from preparers._atomic import _atomic_publish


@dataclass
class TestPreparer:
    name: str = "test"
    source_dir: Path = field(default_factory=Path)
    prepared_dir: Path = field(default_factory=Path)

    def discover(self) -> list[Path]:
        if not self.source_dir.exists():
            return []
        return sorted(self.source_dir.rglob("*.md"))

    def transform(self, src: Path) -> PreparedDoc | None:
        rel = src.relative_to(self.source_dir).as_posix()
        return PreparedDoc(
            relative_path=rel,
            content=src.read_text(encoding="utf-8"),
        )

    def cleanup(self) -> None:
        return

    def run(self, execute: bool = False) -> None:
        if not execute:
            print(f"[test] dry-run (source={self.source_dir})")
            for src in self.discover():
                print(f"  [COPY] {src.relative_to(self.source_dir)}")
            return

        staging = self.prepared_dir.parent / f"_prepared_{self.name}_staging"

        def _build() -> list[PreparedDoc]:
            docs: list[PreparedDoc] = []
            for src in self.discover():
                doc = self.transform(src)
                if doc is None:
                    continue
                print(f"  {src.name} → {doc.relative_path}")
                docs.append(doc)
            return docs

        n = _atomic_publish(self.prepared_dir, staging, _build)
        print(f"[test] prepared {n} files")


PREPARER = TestPreparer()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test framework preparer (standalone)")
    parser.add_argument("--source-root", type=Path, default=Path("data/source"))
    parser.add_argument("--prepared-root", type=Path, default=Path("data/prepared"))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    PREPARER.source_dir = args.source_root / "test"
    PREPARER.prepared_dir = args.prepared_root / "test"
    PREPARER.run(execute=args.execute)