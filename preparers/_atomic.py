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

    # Atomic swap: remove old prepared dir, then rename staging in its place.
    # Staging is always a fresh build, so a crash between removal and rename
    # is safe — the next run rebuilds staging from scratch.
    if prepared_dir.exists():
        shutil.rmtree(prepared_dir)
    staging_dir.rename(prepared_dir)
    return len(docs)
