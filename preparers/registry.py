from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import FrameworkPreparer


_PREPARER_PACKAGES = ("preparers.delta", "preparers.spark", "preparers.test")


def discover_all(source_root: Path, prepared_root: Path) -> list["FrameworkPreparer"]:
    from .base import FrameworkPreparer

    preparers: list[FrameworkPreparer] = []
    for pkg_name in _PREPARER_PACKAGES:
        pkg = importlib.import_module(pkg_name)
        for _finder, module_name, _is_pkg in pkgutil.iter_modules(pkg.__path__):
            if module_name != "prepare":
                continue
            mod = importlib.import_module(f"{pkg_name}.prepare")
            instance = getattr(mod, "PREPARER", None)
            if instance is None:
                continue
            if isinstance(instance, FrameworkPreparer):
                instance.source_dir = source_root / instance.name
                instance.prepared_dir = prepared_root / instance.name
                preparers.append(instance)
    return preparers


def run_all(
    source_root: Path,
    prepared_root: Path,
    execute: bool,
    framework: str | None = None,
) -> None:
    preparers = discover_all(source_root, prepared_root)
    for preparer in preparers:
        if framework and preparer.name != framework:
            continue
        preparer.run(execute=execute)