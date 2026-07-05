from __future__ import annotations

import argparse
from pathlib import Path

from .registry import discover_all


def _default_source_root() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "source"


def _default_prepared_root() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "prepared"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run framework-specific documentation preparers.",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=_default_source_root(),
        help="Root directory with raw framework sources.",
    )
    parser.add_argument(
        "--prepared-root",
        type=Path,
        default=_default_prepared_root(),
        help="Root directory for prepared .md output.",
    )
    parser.add_argument(
        "--framework",
        default=None,
        help="Run only the named framework (default: all registered).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply changes (default: dry-run).",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Skip network downloads (e.g. PySpark HTML pages).",
    )
    args = parser.parse_args()

    preparers = discover_all(args.source_root, args.prepared_root)
    if not preparers:
        print(f"[ERROR] No preparers found under source root: {args.source_root}")
        return

    selected = [p for p in preparers if not args.framework or p.name == args.framework]
    if args.framework and not selected:
        print(f"[ERROR] Framework '{args.framework}' not registered.")
        return

    for preparer in selected:
        if args.no_download and hasattr(preparer, "download_pyspark"):
            preparer.download_pyspark = False
        print(
            f"\n[{preparer.name}] source={preparer.source_dir} prepared={preparer.prepared_dir}"
        )
        preparer.run(execute=args.execute)


if __name__ == "__main__":
    main()
