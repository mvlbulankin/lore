from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from .base import PreparedDoc


def _atomic_publish(
    prepared_dir: Path,
    staging_dir: Path,
    transform_fn: Callable[[], list[PreparedDoc]],
) -> int:
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)

    docs = transform_fn()
    for doc in docs:
        dst = staging_dir / doc.relative_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(doc.content, encoding="utf-8")

    backup = prepared_dir.parent / f"_backup_{prepared_dir.name}"
    if backup.exists():
        shutil.rmtree(backup)
    if prepared_dir.exists():
        prepared_dir.rename(backup)
    staging_dir.rename(prepared_dir)

    if backup.exists():
        shutil.rmtree(backup)
    return len(docs)