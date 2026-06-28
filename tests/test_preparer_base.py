"""Tests for FrameworkPreparer contract and registry."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from preparers.base import FrameworkPreparer, PreparedDoc
from preparers.registry import discover_all


class _FakePreparer:
    name: str = "fake"
    source_dir: Path
    prepared_dir: Path

    def __init__(self, source_dir: Path, prepared_dir: Path) -> None:
        self.source_dir = source_dir
        self.prepared_dir = prepared_dir

    def discover(self) -> list[Path]:
        if not self.source_dir.exists():
            return []
        return sorted(self.source_dir.rglob("*.md"))

    def transform(self, src: Path) -> PreparedDoc | None:
        rel = src.relative_to(self.source_dir).as_posix()
        return PreparedDoc(relative_path=rel, content=src.read_text(encoding="utf-8"))

    def cleanup(self) -> None:
        return

    def run(self, execute: bool = False) -> None:
        from preparers._atomic import _atomic_publish

        if not execute:
            return

        staging = self.prepared_dir.parent / f"_prepared_{self.name}_staging"

        def _build() -> list[PreparedDoc]:
            return [self.transform(p) for p in self.discover() if self.transform(p) is not None]

        _atomic_publish(self.prepared_dir, staging, _build)


@pytest.fixture
def fake_source(tmp_path: Path) -> Path:
    src = tmp_path / "data" / "source" / "fake"
    src.mkdir(parents=True)
    (src / "doc1.md").write_text("# Doc 1\n\nHello world.\n", encoding="utf-8")
    (src / "doc2.md").write_text("# Doc 2\n\nSome content.\n", encoding="utf-8")
    return tmp_path


def test_concrete_preparer_satisfies_protocol(fake_source: Path) -> None:
    source_root = fake_source / "data" / "source"
    prepared_root = fake_source / "data" / "prepared"
    prepared_root.mkdir()
    preparer = _FakePreparer(source_root / "fake", prepared_root / "fake")
    assert isinstance(preparer, FrameworkPreparer)


def test_discover_returns_paths(fake_source: Path) -> None:
    source_root = fake_source / "data" / "source"
    prepared_root = fake_source / "data" / "prepared"
    prepared_root.mkdir()
    preparer = _FakePreparer(source_root / "fake", prepared_root / "fake")
    discovered = preparer.discover()
    assert len(discovered) == 2
    assert all(isinstance(p, Path) for p in discovered)


def test_transform_returns_prepared_doc(fake_source: Path) -> None:
    source_root = fake_source / "data" / "source"
    prepared_root = fake_source / "data" / "prepared"
    prepared_root.mkdir()
    preparer = _FakePreparer(source_root / "fake", prepared_root / "fake")
    src = next(preparer.discover().__iter__())
    doc = preparer.transform(src)
    assert doc is not None
    assert isinstance(doc, PreparedDoc)
    assert doc.relative_path.endswith(".md")
    assert doc.content.startswith("#")


def test_atomic_rename_pattern(fake_source: Path) -> None:
    source_root = fake_source / "data" / "source"
    prepared_root = fake_source / "data" / "prepared"
    prepared_root.mkdir()
    preparer = _FakePreparer(source_root / "fake", prepared_root / "fake")

    preparer.run(execute=True)
    out_files = sorted(p.name for p in (prepared_root / "fake").iterdir())
    assert out_files == ["doc1.md", "doc2.md"]

    leftover = list(prepared_root.glob("_prepared_*"))
    leftover += list(prepared_root.glob("_backup_*"))
    assert leftover == [], f"staging or backup dirs left behind: {leftover}"


def test_dry_run_doesnt_write(fake_source: Path) -> None:
    source_root = fake_source / "data" / "source"
    prepared_root = fake_source / "data" / "prepared"
    prepared_root.mkdir()
    preparer = _FakePreparer(source_root / "fake", prepared_root / "fake")

    preparer.run(execute=False)
    assert not (prepared_root / "fake").exists()


def test_re_execute_replaces_previous(fake_source: Path) -> None:
    source_root = fake_source / "data" / "source"
    prepared_root = fake_source / "data" / "prepared"
    prepared_root.mkdir()
    preparer = _FakePreparer(source_root / "fake", prepared_root / "fake")

    preparer.run(execute=True)
    first = (prepared_root / "fake" / "doc1.md").read_text(encoding="utf-8")
    assert first == "# Doc 1\n\nHello world.\n"

    (source_root / "fake" / "doc1.md").write_text("# Doc 1\n\nUpdated.\n", encoding="utf-8")
    preparer.run(execute=True)
    second = (prepared_root / "fake" / "doc1.md").read_text(encoding="utf-8")
    assert "Updated" in second


def test_registry_discovers_real_preparers(tmp_path: Path) -> None:
    source_root = tmp_path / "data" / "source"
    prepared_root = tmp_path / "data" / "prepared"
    source_root.mkdir(parents=True)
    prepared_root.mkdir(parents=True)

    (source_root / "delta").mkdir()
    (source_root / "spark").mkdir()
    (source_root / "test").mkdir()

    preparers = discover_all(source_root, prepared_root)
    names = {p.name for p in preparers}
    assert {"delta", "spark", "test"}.issubset(names)


def test_registry_filters_by_framework(tmp_path: Path) -> None:
    source_root = tmp_path / "data" / "source"
    prepared_root = tmp_path / "data" / "prepared"
    source_root.mkdir(parents=True)
    prepared_root.mkdir(parents=True)
    for name in ("delta", "spark", "test"):
        (source_root / name).mkdir()

    from preparers.registry import run_all

    (source_root / "test" / "demo.md").write_text("# Demo\n\nText.\n", encoding="utf-8")
    run_all(source_root, prepared_root, execute=True, framework="test")
    assert (prepared_root / "test" / "demo.md").exists()
    assert not (prepared_root / "delta").exists()